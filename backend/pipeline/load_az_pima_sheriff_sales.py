"""Load Pima County, AZ sheriff's sales of real property (scrape_az_pima_sheriff_sales).

Listings use source_system 'az_pima_sheriff_sale', keyed by court case number, status
scheduled on the sale day; the judgment sum is the judgment. The notices are the Sheriff's
complete list of upcoming real property sales, so one that drops off is marked
sold_or_cancelled_unverified.

    python -m pipeline.load_az_pima_sheriff_sales [--dry-run]
"""
import argparse
import json
from datetime import date
from pathlib import Path

from sqlalchemy import text

from app.database.session import engine
from pipeline.sale_listing_loader import Sale, load_sales, usable_address
from pipeline.scrape_az_pima_sheriff_sales import OUTPUT

SOURCE_SYSTEM = "az_pima_sheriff_sale"


def details(sale: dict) -> str:
    lines = [f"Pima County Sheriff's sale of real property under a {sale.get('writ') or 'court writ'}, held at the east"
             " front door of the Pima County Superior Court, 110 West Congress, Tucson, at 10:01 AM on"
             f" {date.fromisoformat(sale['sale_date']):%B %-d, %Y}."]
    if sale.get("judgment"):
        lines.append(f"Judgment sum: ${sale['judgment']:,.2f}, plus interest and costs.")
    lines.append("The sale is subject to the owner's statutory right of redemption, and the Sheriff has done no title"
                 " search: the property may be subject to liens or other interests.")
    lines.append(f"Notice of sale: {sale['notice_url']}")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, default=OUTPUT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    snapshot = json.loads(args.input.read_text())
    pairs = []
    for row in snapshot["sales"]:
        sale = Sale(case=row["case"], street=row["street"], city=row["city"], zip_code=row["zip_code"],
                    sale_date=date.fromisoformat(row["sale_date"]), status="scheduled", raw=row,
                    raw_status=row.get("writ") or "sheriff's sale", judgment=row.get("judgment"))
        if usable_address(sale):
            pairs.append((row, sale))
    if args.dry_run:
        print(f"AZ Pima: {len(pairs)} of {len(snapshot['sales'])} sales with a usable address")
        return 0
    result = load_sales("AZ", "Pima", SOURCE_SYSTEM, snapshot["source_url"], [sale for _, sale in pairs],
                        job="az_pima_sheriff_sales")
    with engine.begin() as connection:
        for row, sale in pairs:
            connection.execute(text("""UPDATE sheriff_sales SET description_text=:details
                WHERE state='AZ' AND county='Pima' AND source_system=:source AND sheriff_number=:number"""),
                {"details": details(row), "source": SOURCE_SYSTEM, "number": sale.case})
    print(f"AZ Pima: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
