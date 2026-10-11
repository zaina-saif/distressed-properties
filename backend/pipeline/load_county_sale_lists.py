"""Load county sale-list snapshots (see scrape_county_sale_lists).

    python -m pipeline.load_county_sale_lists --all
"""
import argparse
import json
from datetime import date

from pipeline.sale_listing_loader import Sale, load_sales, money
from pipeline.scrape_county_sale_lists import COUNTIES, snapshot_path

SOURCE_SYSTEMS = {"KY": "ky_master_commissioner_sale", "OK": "ok_bid4assets_sheriff_sale",
                  "WI": "wi_county_sheriff_sale"}


def date_status(sale_date, today):
    # Still listed after its sale day: the list does not say whether it sold.
    return "scheduled" if sale_date >= today else "sold_or_cancelled_unverified"


def ky_sale(record, today):
    sale_date = date.fromisoformat(record["sale_date"])
    status = "cancelled" if record["withdrawn"] else date_status(sale_date, today)
    return Sale(case=record["case"], street=record["street"], city=record["city"], zip_code=record["zip_code"],
                sale_date=sale_date, status=status, raw=record, raw_status="withdrawn" if record["withdrawn"] else None,
                plaintiff=record["plaintiff"], defendant=record["defendant"], attorney=record["attorney"])


def ok_sale(record, today):
    sale_date = date.fromisoformat(record["sale_date"])
    label = (record["auction_status"] or "").lower()
    if record["stayed"] or "stay" in label or "cancel" in label or "withdraw" in label:
        status = "cancelled"
    elif record["postponed"] or "postpon" in label:
        status = "adjourned"
    else:
        status = date_status(sale_date, today)
    return Sale(case=record["case"], street=record["street"], city=record["city"], zip_code=record["zip_code"],
                sale_date=sale_date, status=status, raw=record, raw_status=record["auction_status"],
                upset=record["minimum_bid"], plaintiff=record["plaintiff"], defendant=record["defendant"],
                attorney=record["attorney"])


def wi_sale(record, today):
    sale_date = date.fromisoformat(record["sale_date"])
    label = (record.get("raw", {}).get("Status") or record["list_status"] or "").lower()
    if "cancel" in label:
        status = "cancelled"
    elif "adjourn" in label:
        status = "adjourned"
    elif "sold" in label or "closed" in label:
        status = "sold"
    else:
        status = date_status(sale_date, today)
    return Sale(case=record["case"], street=record["street"], city=record["city"], zip_code=record["zip_code"],
                sale_date=sale_date, status=status, raw=record, raw_status=record["list_status"],
                upset=money(record.get("opening_bid")), plaintiff=record.get("plaintiff"),
                defendant=record.get("defendant"), attorney=record.get("attorney"),
                property_number=record.get("sale_number"))


TO_SALE = {"KY": ky_sale, "OK": ok_sale, "WI": wi_sale}


def load(state, county):
    snapshot = json.loads(snapshot_path(state, county).read_text())
    today = date.today()
    # A case can be relisted for a later sale; keep its latest listing.
    latest = {}
    for record in snapshot["records"]:
        if record["case"] not in latest or record["sale_date"] >= latest[record["case"]]["sale_date"]:
            latest[record["case"]] = record
    sales = [TO_SALE[state](record, today) for record in latest.values()]
    return load_sales(state, county, SOURCE_SYSTEMS[state], snapshot["source_url"], sales,
                      job=f"{state.lower()}_{county.lower()}_sale_list")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--counties", nargs="+", metavar="ST:County")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    keys = sorted(COUNTIES) if args.all else [tuple(value.split(":", 1)) for value in args.counties or []]
    for state, county in keys:
        if not snapshot_path(state, county).exists():
            print(f"{state} {county}: no snapshot, skipped")
            continue
        print(f"{state} {county}: {load(state, county)}")


if __name__ == "__main__":
    main()
