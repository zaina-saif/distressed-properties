"""Load the Clark County, NV treasurer trustee auction (scrape_nv_clark_tax_auction) as sale listings.

Listings use source_system 'nv_clark_treasurer_tax_sale', keyed by parcel number, sale type
"Tax-defaulted property sale" (the dashboard's "Tax sales" filter), with the parcel layer's
map position. The minimum bid is the opening bid. Status, from the auction list:

  before the auction       scheduled on the auction date (a parcel struck from the list is cancelled:
                           the taxes were paid or it was withdrawn)
  after it, a winning bid  sold for that bid
  after it, struck, no bid cancelled (removed before the sale)
  after it, neither        unsold (offered, no winning bid at either session)

The list is the auction's complete parcel list, so a parcel that drops off is marked
sold_or_cancelled_unverified.

    python -m pipeline.load_nv_clark_tax_auction [--dry-run]
"""
import argparse
import json
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import text

from app.database.session import engine
from pipeline.sale_listing_loader import Sale, load_sales, usable_address
from pipeline.scrape_nv_clark_tax_auction import OUTPUT

SOURCE_SYSTEM = "nv_clark_treasurer_tax_sale"


def auction_day(snapshot: dict) -> date | None:
    starts = [session["start"] for session in snapshot["sessions"] if session.get("start")]
    return datetime.fromisoformat(min(starts)).date() if starts else None


def status_of(parcel: dict, sale_day: date | None, today: date) -> tuple[str, str]:
    if sale_day is None or sale_day >= today:
        return ("cancelled", "struck from the auction list") if parcel["struck"] else ("scheduled", "treasurer trustee auction")
    if parcel.get("winning_bid"):
        return "sold", f"sold at the treasurer's auction for ${parcel['winning_bid']:,.2f}"
    if parcel["struck"]:
        return "cancelled", "struck from the auction list without a winning bid"
    return "unsold", "offered at the auction with no winning bid"


def details(parcel: dict, snapshot: dict) -> str:
    sale_day = auction_day(snapshot)
    place = snapshot["sessions"][0]["place"] if snapshot["sessions"] else "the Clark County Government Center"
    lines = ["Clark County Treasurer trustee auction: property held in trust by the Treasurer after three years of"
             " unpaid property taxes, sold at a public auction.",
             f"Auction: {sale_day:%B %-d, %Y} at 8:00 a.m., in person at {place}; unpaid and unsold parcels may be"
             " re-auctioned at 2:00 p.m. the same day." if sale_day else f"Auction held in person at {place}."]
    if parcel.get("minimum_bid"):
        lines.append(f"Minimum bid: ${parcel['minimum_bid']:,.2f}.")
    if parcel.get("winning_bid"):
        lines.append(f"Winning bid: ${parcel['winning_bid']:,.2f}.")
    lines.append("Bidders register with a $5,000 deposit and pay in certified funds (cash, cashier's check, wire or"
                 " money order) on the day of the auction.")
    lines.append(f"Parcel {parcel['parcel']}. City and ZIP come from the county's parcel map.")
    return "\n".join(lines)


def sales_from(snapshot: dict, today: date) -> list[tuple[dict, Sale]]:
    sale_day, pairs = auction_day(snapshot), []
    for parcel in snapshot["parcels"]:
        status, raw_status = status_of(parcel, sale_day, today)
        sale = Sale(case=parcel["parcel"], street=parcel.get("street") or "", city=parcel.get("city"),
                    zip_code=parcel.get("zip_code"), sale_date=sale_day, status=status, raw=parcel,
                    raw_status=raw_status, upset=parcel.get("minimum_bid"), parcel=parcel["parcel"],
                    latitude=parcel.get("latitude"), longitude=parcel.get("longitude"))
        if usable_address(sale):
            pairs.append((parcel, sale))
    return pairs


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, default=OUTPUT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    snapshot = json.loads(args.input.read_text())
    pairs = sales_from(snapshot, date.today())
    if args.dry_run:
        counts: dict[str, int] = {}
        for _, sale in pairs:
            counts[sale.status] = counts.get(sale.status, 0) + 1
        print(f"Clark: {len(pairs)} of {len(snapshot['parcels'])} parcels with an address {counts}")
        return 0
    result = load_sales("NV", "Clark", SOURCE_SYSTEM, snapshot["source_url"], [sale for _, sale in pairs],
                        job="nv_clark_treasurer_tax_auction")
    with engine.begin() as connection:
        for parcel, sale in pairs:
            sold = sale.status == "sold"
            connection.execute(text("""UPDATE sheriff_sales SET description_text=:details,
                    sold_amount=:amount, sold_on=:sold_on, sold_raw_status=:raw
                WHERE state='NV' AND county='Clark' AND source_system=:source AND sheriff_number=:number"""),
                {"details": details(parcel, snapshot), "source": SOURCE_SYSTEM, "number": sale.case,
                 "amount": parcel.get("winning_bid") if sold else None, "sold_on": sale.sale_date if sold else None,
                 "raw": sale.raw_status if sold else None})
    print(f"NV Clark: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
