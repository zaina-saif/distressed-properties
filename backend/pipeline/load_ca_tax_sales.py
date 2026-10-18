"""Load California county tax-defaulted property sales (scrape_ca_tax_sales) as sale listings.

Each county's open parcels are a complete list for its sale, so a parcel that drops off
before the sale closes (redeemed or withdrawn) is marked sold_or_cancelled_unverified.
The minimum bid is the opening bid (the county sets it to at least the taxes, penalties
and costs owed); parcels without a street address (mostly vacant land) are not loaded.

    python -m pipeline.load_ca_tax_sales
    python -m pipeline.load_ca_tax_sales --dry-run
"""
import argparse
import json
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import text

from app.database.session import engine
from pipeline.sale_listing_loader import Sale, load_sales, usable_address
from pipeline.scrape_ca_tax_sales import OUTPUT

SOURCE_SYSTEM = "ca_bid4assets_tax_sale"


def _when(value: str | None) -> str | None:
    if not value:
        return None
    moment = datetime.fromisoformat(value)
    return moment.strftime("%B %-d, %Y at %-I:%M %p ET")


def details(parcel: dict, sale: dict) -> str:
    lines = [f"California tax-defaulted property sale: {sale['title']}, run by the county tax collector on Bid4Assets.",
             f"Online bidding opens {_when(parcel.get('opens'))} and this parcel's auction closes"
             f" {_when(parcel.get('closes'))} (it stays open while bids keep coming in the last minutes)."]
    if parcel.get("minimum_bid"):
        lines.append(f"Minimum bid: ${parcel['minimum_bid']:,.2f}, set by the county to at least the unpaid taxes,"
                     " penalties and costs. Bidders need a deposit with Bid4Assets before the sale.")
    if parcel.get("apn"):
        lines.append(f"APN {parcel['apn']}.")
    lines.append(f"Auction page: {parcel['auction_url']}")
    return "\n".join(lines)


def sales_by_county(snapshot: dict) -> dict[str, tuple[dict, list[Sale]]]:
    counties = {}
    for sale in snapshot["sales"]:
        listings = counties.setdefault(sale["county"], (sale, []))[1]
        for parcel in sale["parcels"]:
            listing = Sale(case=parcel["case"], street=(parcel.get("street") or "").title(), city=parcel.get("city"),
                           zip_code=parcel.get("zip_code"), sale_date=date.fromisoformat(parcel["sale_date"]),
                           status="scheduled", raw=parcel, raw_status="tax-defaulted property auction",
                           upset=parcel.get("minimum_bid"), parcel=parcel.get("apn"),
                           property_number=str(parcel["auction_id"]))
            if usable_address(listing):
                listings.append(listing)
    return counties


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, default=OUTPUT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    snapshot = json.loads(args.input.read_text())
    for county, (sale, listings) in sales_by_county(snapshot).items():
        if args.dry_run:
            print(f"CA {county}: {len(listings)} of {len(sale['parcels'])} parcels with an address")
            continue
        result = load_sales("CA", county, SOURCE_SYSTEM, sale["url"], listings,
                            job=f"ca_{county.lower().replace(' ', '_')}_tax_sale")
        parcels = {parcel["case"]: parcel for parcel in sale["parcels"]}
        with engine.begin() as connection:
            for listing in listings:
                connection.execute(text("""UPDATE sheriff_sales SET description_text=:details
                    WHERE state='CA' AND county=:county AND source_system=:source AND sheriff_number=:number"""),
                    {"details": details(parcels[listing.case], sale), "county": county, "source": SOURCE_SYSTEM,
                     "number": listing.case})
        print(f"CA {county}: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
