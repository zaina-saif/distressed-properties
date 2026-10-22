"""Load the Hutchens Law Firm's pending North Carolina foreclosure sales (scrape_nc_hutchens_sales).

Listings use source_system 'nc_hutchens_foreclosure_sale', keyed by the firm's file number,
status scheduled_unverified (read as date_passed_unverified once the date passes: the list
publishes no results, and North Carolina sales are often postponed). The lender's opening
bid, posted the day before the sale, is the minimum bid. Each county's listings are the
firm's complete list for it, so a sale that drops off (sold, postponed out of the list or
cancelled) is marked sold_or_cancelled_unverified, including in a county left with none.

    python -m pipeline.load_nc_hutchens_sales [--dry-run]
"""
import argparse
import json
from datetime import date
from pathlib import Path

from sqlalchemy import text

from app.database.session import engine
from pipeline.sale_listing_loader import Sale, load_sales, money, usable_address
from pipeline.scrape_nc_hutchens_sales import OUTPUT

SOURCE_SYSTEM = "nc_hutchens_foreclosure_sale"


def details(sale: dict) -> str:
    lines = ["North Carolina foreclosure sale (power of sale) handled by Hutchens Law Firm as substitute trustee's"
             " counsel, held at the county courthouse.",
             f"Sale date: {date.fromisoformat(sale['sale_date']):%B %-d, %Y}. North Carolina sales are often"
             " postponed; check the notice of sale with the Clerk of Superior Court before the sale."]
    if sale.get("opening_bid"):
        lines.append(f"Opening bid: {sale['opening_bid']} (the lender's bid, posted the day before the sale).")
    else:
        lines.append("The opening bid is posted the day before the sale.")
    lines.append("After the sale, anyone may upset the bid by at least 5% (minimum $750) within ten days;"
                 " each upset bid starts a new ten-day period.")
    if sale.get("sp_number"):
        lines.append(f"Special proceeding {sale['sp_number']}.")
    if sale.get("deed_of_trust"):
        lines.append(f"Deed of trust book/page {sale['deed_of_trust']}.")
    return "\n".join(lines)


def sales_by_county(snapshot: dict) -> dict[str, list[tuple[dict, Sale]]]:
    counties: dict[str, list[tuple[dict, Sale]]] = {}
    for sale in snapshot["sales"]:
        listing = Sale(case=sale["case"], street=(sale.get("street") or "").title(), city=sale.get("city"),
                       zip_code=sale.get("zip_code"), sale_date=date.fromisoformat(sale["sale_date"]),
                       status="scheduled_unverified", raw=sale, raw_status="pending foreclosure sale",
                       upset=money(sale.get("opening_bid")), property_number=sale.get("sp_number"))
        if usable_address(listing):
            counties.setdefault(sale["county"], []).append((sale, listing))
    return counties


def open_counties() -> set[str]:
    with engine.connect() as connection:
        return set(connection.execute(text("""SELECT DISTINCT county FROM sheriff_sales
            WHERE state='NC' AND source_system=:source
              AND current_status IN ('scheduled','scheduled_unverified')"""), {"source": SOURCE_SYSTEM}).scalars())


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, default=OUTPUT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    snapshot = json.loads(args.input.read_text())
    counties = sales_by_county(snapshot)
    if args.dry_run:
        for county, pairs in sorted(counties.items()):
            print(f"NC {county}: {len(pairs)}")
        print(f"{sum(map(len, counties.values()))} of {len(snapshot['sales'])} sales with a usable address")
        return 0
    for county in sorted(set(counties) | open_counties()):
        pairs = counties.get(county, [])
        result = load_sales("NC", county, SOURCE_SYSTEM, snapshot["source_url"], [listing for _, listing in pairs],
                            job=f"nc_{county.lower().replace(' ', '_')}_hutchens_sales")
        with engine.begin() as connection:
            for sale, listing in pairs:
                connection.execute(text("""UPDATE sheriff_sales SET description_text=:details
                    WHERE state='NC' AND county=:county AND source_system=:source AND sheriff_number=:number"""),
                    {"details": details(sale), "county": county, "source": SOURCE_SYSTEM, "number": listing.case})
        print(f"NC {county}: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
