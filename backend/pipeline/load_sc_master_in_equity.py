"""Load South Carolina Master-in-Equity snapshots (see scrape_sc_master_in_equity).

    python -m pipeline.load_sc_master_in_equity --all
"""
import argparse
import json
from datetime import date

from pipeline.sale_listing_loader import Sale, load_sales, money
from pipeline.scrape_sc_master_in_equity import COUNTIES, snapshot_path

SOURCE_SYSTEM = "sc_master_in_equity_sale"


def to_sale(record, today):
    sale_date = date.fromisoformat(record["sale_date"])
    if record["withdrawn"]:
        status = "cancelled"
    elif sale_date >= today:
        status = "scheduled"
    else:
        # Still on the list after its sale day: the list does not say whether it sold.
        status = "sold_or_cancelled_unverified"
    return Sale(case=record["case"], street=record["street"], city=record["city"], zip_code=record["zip_code"],
                sale_date=sale_date, status=status, raw=record, raw_status="withdrawn" if record["withdrawn"] else None,
                parcel=record["parcel"], judgment=money(record["judgment"]), plaintiff=record["plaintiff"],
                defendant=record["defendant"], attorney=record["attorney"], result=record.get("lien"))


def load(county):
    snapshot = json.loads(snapshot_path(county).read_text())
    today = date.today()
    # A case can be relisted for a later sale; keep its latest listing.
    latest = {}
    for record in snapshot["records"]:
        if record["case"] not in latest or record["sale_date"] >= latest[record["case"]]["sale_date"]:
            latest[record["case"]] = record
    sales = [to_sale(record, today) for record in latest.values()]
    return load_sales("SC", county, SOURCE_SYSTEM, snapshot["source_url"], sales, job=f"sc_mie_{county.lower()}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--counties", nargs="+", choices=sorted(COUNTIES))
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    for county in sorted(COUNTIES) if args.all else args.counties or []:
        if not snapshot_path(county).exists():
            print(f"SC {county}: no snapshot, skipped")
            continue
        print(f"SC {county}: {load(county)}")


if __name__ == "__main__":
    main()
