"""Load Georgia county tax sales (scrape_ga_tax_sales) as sale listings.

Listings use source_system 'ga_county_tax_sale', keyed by the parcel ID as printed, status
scheduled on the sale day, sale type "Tax sale (redeemable deed)" (the dashboard's "Tax
sales" filter), with the parcel layer's address and map position. Cobb's starting bid is
the minimum bid; Fulton's list gives none. A county's list is complete for its sale, so a
parcel that drops off (paid, or the sale is over and the next list replaced it) is marked
sold_or_cancelled_unverified; a county whose scrape failed keeps its previous rows.

    python -m pipeline.load_ga_tax_sales [--dry-run]
"""
import argparse
import json
from datetime import date
from pathlib import Path

from sqlalchemy import text

from app.database.session import engine
from pipeline.sale_listing_loader import Sale, load_sales, usable_address
from pipeline.scrape_ga_tax_sales import COUNTIES, OUTPUT

SOURCE_SYSTEM = "ga_county_tax_sale"
SELLERS = {"Fulton": "the Fulton County Sheriff's Office (tax / levy sale)", "Cobb": "the Cobb County Tax Commissioner"}


def details(parcel: dict) -> str:
    lines = [f"Georgia tax sale held by {SELLERS[parcel['county']]} at the courthouse on"
             f" {date.fromisoformat(parcel['sale_date']):%B %-d, %Y} (the first Tuesday of the month).",
             "The list changes until the sale: parcels whose taxes are paid are removed."]
    if parcel.get("starting_bid"):
        lines.append(f"Starting bid: ${parcel['starting_bid']:,.2f} (taxes, penalties and costs; the payoff may vary).")
    if parcel.get("sale_number"):
        lines.append(f"Sheriff's sale number {parcel['sale_number']}.")
    lines.append("The buyer receives a tax deed the owner can redeem, usually within 12 months, by paying the price"
                 " plus a premium; the buyer cannot take possession until the redemption right is foreclosed.")
    lines.append(f"Parcel {parcel['parcel']}. Address and map position from the county's parcel map; list: {parcel['list_url']}")
    return "\n".join(lines)


def sales_by_county(snapshot: dict) -> dict[str, list[tuple[dict, Sale]]]:
    counties: dict[str, list[tuple[dict, Sale]]] = {}
    for parcel in snapshot["parcels"]:
        sale = Sale(case=parcel["parcel"], street=(parcel.get("street") or "").title(), city=parcel.get("city"),
                    zip_code=parcel.get("zip_code"), sale_date=date.fromisoformat(parcel["sale_date"]),
                    status="scheduled", raw=parcel, raw_status="tax sale", upset=parcel.get("starting_bid"),
                    parcel=parcel["parcel"], property_number=parcel.get("sale_number"),
                    latitude=parcel.get("latitude"), longitude=parcel.get("longitude"))
        if usable_address(sale):
            counties.setdefault(parcel["county"], []).append((parcel, sale))
    return counties


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, default=OUTPUT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    snapshot = json.loads(args.input.read_text())
    counties = sales_by_county(snapshot)
    for county in snapshot["counties"]:
        pairs = counties.get(county, [])
        if args.dry_run:
            print(f"GA {county}: {len(pairs)} of {sum(p['county'] == county for p in snapshot['parcels'])} parcels"
                  " with a usable address")
            continue
        if county in snapshot.get("failed", []):
            print(f"GA {county}: scrape failed, left as it was")
            continue
        source_url = COUNTIES[county].page
        result = load_sales("GA", county, SOURCE_SYSTEM, source_url, [sale for _, sale in pairs],
                            job=f"ga_{county.lower()}_tax_sale")
        with engine.begin() as connection:
            for parcel, sale in pairs:
                connection.execute(text("""UPDATE sheriff_sales SET description_text=:details
                    WHERE state='GA' AND county=:county AND source_system=:source AND sheriff_number=:number"""),
                    {"details": details(parcel), "county": county, "source": SOURCE_SYSTEM, "number": sale.case})
        print(f"GA {county}: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
