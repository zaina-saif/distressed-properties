"""Load Tarrant County, TX constable's tax foreclosure sales (scrape_tx_tarrant_tax_sales).

Listings use source_system 'tx_tarrant_constable_tax_sale', keyed by TAD account and sale day
(an account can be on two months' lists), status scheduled, sale type "Tax foreclosure sale
(sheriff/constable)" with the Texas redemption warning. The lists publish no bids. The
monthly pages are the complete list of upcoming sales, so an account that drops off
(withdrawn or paid) is marked sold_or_cancelled_unverified.

    python -m pipeline.load_tx_tarrant_tax_sales [--dry-run]
"""
import argparse
import json
from datetime import date
from pathlib import Path

from sqlalchemy import text

from app.database.session import engine
from pipeline.sale_listing_loader import Sale, load_sales, usable_address
from pipeline.scrape_tx_tarrant_tax_sales import OUTPUT

SOURCE_SYSTEM = "tx_tarrant_constable_tax_sale"


def details(sale: dict) -> str:
    return "\n".join([
        f"Tarrant County delinquent property tax sale by Constable Precinct 3 on {date.fromisoformat(sale['sale_date']):%B %-d, %Y}"
        " (first Tuesday of the month), at the Tarrant County Courthouse.",
        f"Tax suit (cause) {sale['cause']}; Tarrant Appraisal District account {sale['account']}. Status on the list: {sale['status']}.",
        "The list publishes no minimum bid; the tax firm's notice of sale gives it.",
        "The former owner can buy the property back after the sale: within 2 years for a homestead or agricultural"
        " land and 180 days for other property. Get a professional title search before bidding.",
        f"Address from the appraisal district's records for the account. List: {sale['list_url']}"])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, default=OUTPUT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    snapshot = json.loads(args.input.read_text())
    pairs = []
    for row in snapshot["sales"]:
        sale = Sale(case=f"{row['account']}:{row['sale_date']}", street=row["street"].title(), city=row["city"],
                    zip_code=None, sale_date=date.fromisoformat(row["sale_date"]), status="scheduled", raw=row,
                    raw_status=row["status"].lower(), property_number=row["account"])
        if usable_address(sale):
            pairs.append((row, sale))
    if args.dry_run:
        print(f"TX Tarrant: {len(pairs)} of {len(snapshot['sales'])} sales with a usable address")
        return 0
    result = load_sales("TX", "Tarrant", SOURCE_SYSTEM, snapshot["source_url"], [sale for _, sale in pairs],
                        job="tx_tarrant_constable_tax_sales")
    with engine.begin() as connection:
        for row, sale in pairs:
            connection.execute(text("""UPDATE sheriff_sales SET description_text=:details, docket_number=:cause
                WHERE state='TX' AND county='Tarrant' AND source_system=:source AND sheriff_number=:number"""),
                {"details": details(row), "cause": row["cause"], "source": SOURCE_SYSTEM, "number": sale.case})
    print(f"TX Tarrant: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
