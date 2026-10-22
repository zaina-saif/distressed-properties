"""Load North Carolina tax foreclosure sales from Zacchaeus Legal Services (scrape_nc_zls_tax_foreclosures).

Listings use source_system 'nc_zls_tax_foreclosure', keyed by tax office and parcel
number, sale type "Tax foreclosure sale" (the dashboard's "Tax sales" filter). Status, from
the site's own:

  Courthouse Sale            -> scheduled on the sale date; the opening bid is the minimum bid
  Upset Bidding in Progress  -> scheduled on the upset-bid deadline; the current bid is the bid to beat
  Resale Pending             -> scheduled_unverified (a resale is due; its date is not listed yet)
  Pending Confirmation, Sale Confirmed, Sale Confirmed / Deed Recorded
                             -> sold on the sale date for the current bid
  Redeemed                   -> redeemed (the owner paid the taxes)

Each county's parcels are ZLS's complete list for it, so a parcel that drops off is marked
sold_or_cancelled_unverified. Parcels without an address (often vacant land) are not loaded.

    python -m pipeline.load_nc_zls_tax_foreclosures [--dry-run]
"""
import argparse
import json
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import text

from app.database.session import engine
from pipeline.sale_listing_loader import Sale, load_sales, money, usable_address
from pipeline.scrape_nc_zls_tax_foreclosures import OUTPUT

SOURCE_SYSTEM = "nc_zls_tax_foreclosure"
SOLD = {"Pending Confirmation", "Sale Confirmed", "Sale Confirmed / Deed Recorded"}


def deadline(parcel: dict) -> date | None:
    value = parcel.get("upset_deadline")
    return datetime.strptime(value.split()[0], "%m/%d/%Y").date() if value else None


def status_of(parcel: dict) -> tuple[str, date | None, str, float | None] | None:
    """Status, the date it belongs to, the raw status and the bid to show; None for a status not known here."""
    sale_date = date.fromisoformat(parcel["sale_date"]) if parcel.get("sale_date") else None
    status = parcel["status"]
    if status == "Courthouse Sale":
        return "scheduled", sale_date, "courthouse sale", money(parcel.get("opening_bid"))
    if status == "Upset Bidding in Progress" and deadline(parcel):
        bid = parcel.get("current_bid") or "not listed"
        return ("scheduled", deadline(parcel), f"upset bidding open until {parcel['upset_deadline']}; current bid {bid}",
                money(parcel.get("current_bid")))
    if status == "Resale Pending":
        return "scheduled_unverified", sale_date, "resale pending", money(parcel.get("opening_bid"))
    if status in SOLD:
        return "sold", sale_date, status.lower(), money(parcel.get("current_bid"))
    if status == "Redeemed":
        return "redeemed", sale_date, "redeemed", None
    return None


def details(parcel: dict) -> str:
    office = parcel["tax_office"]
    lines = [f"North Carolina tax foreclosure sale for the {office}, handled by Zacchaeus Legal Services."
             " The county sells the property at the courthouse to collect unpaid property taxes.",
             f"Status on the firm's list: {parcel['status']}."]
    if parcel.get("sale_date"):
        lines.append(f"Sale date: {date.fromisoformat(parcel['sale_date']):%B %-d, %Y}.")
    if parcel.get("opening_bid"):
        lines.append(f"Opening bid: {parcel['opening_bid']}.")
    if parcel.get("upset_deadline"):
        lines.append(f"Upset bids are open until {parcel['upset_deadline']}; current bid {parcel.get('current_bid') or 'not listed'}.")
    lines.append("After the sale, anyone may upset the bid by at least 5% (minimum $750) within ten days; each upset"
                 " bid starts a new ten-day period, and the Clerk of Superior Court then confirms the sale.")
    lines.append(f"Parcel {parcel['parcel']}. The firm notes that addresses come from others and are not certified;"
                 " the legal description in the notice of sale governs.")
    return "\n".join(lines)


def sales_by_county(snapshot: dict) -> tuple[dict[str, list[tuple[dict, Sale]]], list[str]]:
    counties: dict[str, list[tuple[dict, Sale]]] = {}
    unknown = []
    for parcel in snapshot["parcels"]:
        found = status_of(parcel)
        if found is None or not parcel.get("county"):
            unknown.append(f"{parcel['tax_office']} {parcel['parcel']}: {parcel['status']}")
            continue
        status, sale_date, raw_status, bid = found
        listing = Sale(case=f"{parcel['tax_office']}:{parcel['parcel']}", street=parcel.get("street") or "",
                       city=parcel.get("city"), zip_code=parcel.get("zip_code"), sale_date=sale_date, status=status,
                       raw=parcel, raw_status=raw_status, upset=bid if status != "sold" else None,
                       parcel=parcel["parcel"], result=parcel["status"])
        if usable_address(listing):
            counties.setdefault(parcel["county"], []).append((parcel, listing))
    return counties, unknown


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
    counties, unknown = sales_by_county(snapshot)
    for line in unknown:
        print(f"ZLS: not loaded ({line})")
    if args.dry_run:
        for county, pairs in sorted(counties.items()):
            print(f"NC {county}: {len(pairs)} ({sum(sale.status == 'scheduled' for _, sale in pairs)} scheduled)")
        return 0
    for county in sorted(set(counties) | open_counties()):
        pairs = counties.get(county, [])
        result = load_sales("NC", county, SOURCE_SYSTEM, snapshot["source_url"], [sale for _, sale in pairs],
                            job=f"nc_{county.lower().replace(' ', '_')}_zls_tax_foreclosures")
        with engine.begin() as connection:
            for parcel, sale in pairs:
                sold = sale.status == "sold"
                connection.execute(text("""UPDATE sheriff_sales SET description_text=:details,
                        sold_amount=:amount, sold_on=:sold_on, sold_raw_status=:raw
                    WHERE state='NC' AND county=:county AND source_system=:source AND sheriff_number=:number"""),
                    {"details": details(parcel), "county": county, "source": SOURCE_SYSTEM, "number": sale.case,
                     "amount": money(parcel.get("current_bid")) if sold else None,
                     "sold_on": sale.sale_date if sold else None, "raw": sale.raw_status if sold else None})
        print(f"NC {county}: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
