"""Load an Illinois county sheriff's posted foreclosure sales list (Kane, ...) as sale listings.

Snapshots (data/sheriff_sales/il_<county>_sheriff_sales.json) list each sale's sheriff's
number, chancery (court case) number, sale date, street, town and judgment. Listings use
source_system 'il_county_sheriff_sale', keyed by sheriff's number, status scheduled; the
list is the county's complete set of upcoming sales, so a sale that drops off is marked
sold_or_cancelled_unverified. ZIPs and map positions come from fill_missing_zips.

    python -m pipeline.load_il_county_sheriff_sales --county Kane [--dry-run]
"""
import argparse
import json
from datetime import date
from pathlib import Path

from pipeline.sale_listing_loader import Sale, load_sales, usable_address

SOURCE_SYSTEM = "il_county_sheriff_sale"


def snapshot_path(county: str) -> Path:
    return Path(f"data/sheriff_sales/il_{county.lower().replace(' ', '_')}_sheriff_sales.json")


def to_sales(snapshot: dict) -> list[Sale]:
    sales = []
    for row in snapshot["sales"]:
        sale = Sale(case=row["sheriff_number"], street=(row.get("street") or "").title(), city=row.get("city"),
                    zip_code=row.get("zip_code"), sale_date=date.fromisoformat(row["sale_date"]), status="scheduled",
                    raw=row, raw_status="sheriff's foreclosure sale", judgment=row.get("judgment"),
                    upset=row.get("opening_bid"), property_number=row.get("chancery_number"))
        if usable_address(sale):
            sales.append(sale)
    return sales


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--county", required=True)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    snapshot = json.loads((args.input or snapshot_path(args.county)).read_text())
    sales = to_sales(snapshot)
    if args.dry_run:
        print(f"IL {snapshot['county']}: {len(sales)} of {len(snapshot['sales'])} sales with a usable address")
        return 0
    result = load_sales("IL", snapshot["county"], SOURCE_SYSTEM, snapshot["source_url"], sales,
                        job=f"il_{snapshot['county'].lower().replace(' ', '_')}_sheriff_sales")
    print(f"IL {snapshot['county']}: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
