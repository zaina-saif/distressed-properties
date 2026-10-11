"""Load county sale-list snapshots (see scrape_county_sale_lists).

    python -m pipeline.load_county_sale_lists --all
"""
import argparse
import json
from datetime import date

from pipeline.sale_listing_loader import Sale, load_sales, money
from pipeline.scrape_county_sale_lists import COUNTIES, snapshot_path



def date_status(sale_date, today):
    # Still listed after its sale day: the list does not say whether it sold.
    return "scheduled" if sale_date >= today else "sold_or_cancelled_unverified"


def ky_sale(record, today):
    sale_date = date.fromisoformat(record["sale_date"])
    status = "cancelled" if record["withdrawn"] else date_status(sale_date, today)
    return Sale(case=record["case"], street=record["street"], city=record["city"], zip_code=record["zip_code"],
                sale_date=sale_date, status=status, raw=record, raw_status="withdrawn" if record["withdrawn"] else None,
                plaintiff=record["plaintiff"], defendant=record["defendant"], attorney=record["attorney"])


def bid4assets_sale(record, today):
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
                upset=record["minimum_bid"], parcel=record.get("parcel"), plaintiff=record["plaintiff"],
                defendant=record["defendant"], attorney=record["attorney"])


def tulsa_sale(record, today):
    sale_date = date.fromisoformat(record["sale_date"])
    price = money(str(record["sale_price"])) if record["sale_price"] not in (None, "") else None
    result = None
    if record["recalled"]:
        status = "cancelled"
    elif sale_date >= today:
        status = "scheduled"
    elif price:
        status, result = "sold", f"Sold for ${price:,.2f}"
    else:
        status = "sold_or_cancelled_unverified"
        result = "No bid" if record["no_bid"] else "No sale" if record["no_sale"] else None
    raw_status = "recalled" if record["recalled"] else "no sale" if record["no_sale"] else "no bid" if record["no_bid"] else None
    return Sale(case=record["case"], street=record["street"], city=record["city"], zip_code=record["zip_code"],
                sale_date=sale_date, status=status, raw=record, raw_status=raw_status, plaintiff=record["plaintiff"],
                defendant=record["defendant"], attorney=record["attorney"], result=result)


def sd_sale(record, today):
    sale_date = date.fromisoformat(record["sale_date"])
    return Sale(case=record["case"], street=record["street"], city=record["city"], zip_code=record["zip_code"],
                sale_date=sale_date, status=date_status(sale_date, today), raw=record,
                judgment=money(record["judgment"]), plaintiff=record["plaintiff"], defendant=record["defendant"],
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


# (source_system, record -> Sale) per county; a county keeps its source_system so reloads update its rows.
SOURCES = {("KY", "Jefferson"): ("ky_master_commissioner_sale", ky_sale),
           ("OK", "Oklahoma"): ("ok_bid4assets_sheriff_sale", bid4assets_sale),
           ("OK", "Tulsa"): ("ok_tulsa_sheriff_sale", tulsa_sale),
           ("SD", "Minnehaha"): ("sd_county_sheriff_sale", sd_sale),
           ("WI", "Dane"): ("wi_county_sheriff_sale", wi_sale),
           ("WI", "Milwaukee"): ("wi_bid4assets_sheriff_sale", bid4assets_sale)}


def load(state, county):
    snapshot = json.loads(snapshot_path(state, county).read_text())
    today = date.today()
    # A case can be relisted for a later sale; keep its latest listing.
    latest = {}
    for record in snapshot["records"]:
        if record["case"] not in latest or record["sale_date"] >= latest[record["case"]]["sale_date"]:
            latest[record["case"]] = record
    source, to_sale = SOURCES[(state, county)]
    sales = [to_sale(record, today) for record in latest.values()]
    return load_sales(state, county, source, snapshot["source_url"], sales,
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
