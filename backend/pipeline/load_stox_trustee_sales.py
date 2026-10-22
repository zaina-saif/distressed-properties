"""Load the STOX "Today's Sales" export (output/stox-todays-sales.json) as trustee-sale listings.

STOX Posting and Publishing posts and auctions non-judicial trustee sales (CA, AZ, AK,
OR, UT, WA) for trustees such as Clear Recon. Its terms (section 13) allow no commercial
use without STOX's written consent; the operator has it (October 2026). Loading anywhere
but a local database (the docker compose db) needs --stox-consent to say so.

Only these export fields are stored, raw payload included: Property Address, Opening
Bid, Trustee, State, Sale Postponed to:, Sales Results, Winning Bid, plus County, Date of
Sale and STOX# to place, date and key the listing. Executed By (borrower names), Tax ID,
Trustee Sale Notes, contact details and the disclaimer are left out.

Status, from what is kept:
  Sales Results "Sold 3rd Party"      -> sold, buyer third_party, winning bid as sold_amount
  Sales Results "Back to Beneficiary" -> sold, buyer plaintiff (the lender took it back)
  Sale Postponed to: <date>           -> scheduled on that date; the original date is recorded as adjourned
  neither                             -> sold_or_cancelled_unverified (cancelled and indefinitely postponed
                                         sales look alike without the notes)

    DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5433/sheriff_sales python -m pipeline.load_stox_trustee_sales
    python -m pipeline.load_stox_trustee_sales --stox-consent   # production (backend/.env DATABASE_URL)
    python -m pipeline.load_stox_trustee_sales --dry-run
"""
import argparse
import json
import re
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import text

from app.database.session import engine
from pipeline.sale_listing_loader import Sale, load_sales, money, usable_address

SOURCE_SYSTEM = "stox_trustee_sale"
INPUT = Path(__file__).resolve().parents[2] / "output" / "stox-todays-sales.json"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "db"}
KEPT_FIELDS = ["STOX#", "State", "County", "Date of Sale", "Property Address", "Opening Bid", "Trustee",
               "Sale Postponed to:", "Sales Results", "Winning Bid"]
STATES = {"Oregon": "OR", "Washington": "WA", "California": "CA", "Arizona": "AZ", "Alaska": "AK", "Utah": "UT",
          "Nevada": "NV", "Idaho": "ID"}
BUYERS = {"Sold 3rd Party": "third_party", "Back to Beneficiary": "plaintiff"}


def mdy(value: str) -> date | None:
    return datetime.strptime(value, "%m-%d-%Y").date() if value else None


def split_address(address: str) -> tuple[str, str | None, str | None]:
    """'2736 E MARGUERITE AVE, PHOENIX, Arizona 85040 Maricopa' -> street, city, ZIP.

    The last part is "<State> <ZIP> <County or United States>"; the city precedes it.
    A street given twice ("6 TANGLEWOOD PLACE AKA, 250 FOREST RIDGE ROAD #6") or two
    parcels ("1616 OLD WOMAN SPRINGS RD. AND, 57585 ...") keeps the first address."""
    parts = [re.sub(r"\s+", " ", part).strip() for part in address.split(",")]
    zip_match = re.search(r"\b(\d{5})(?:-\d{4})?\b", parts[-1])
    street = re.sub(r"\s+(?:AKA|AND)$", "", parts[0], flags=re.IGNORECASE)
    city = parts[-2] if len(parts) >= 3 else None
    return street, city, zip_match.group(1) if zip_match else None


def status_of(listing: dict) -> tuple[str, date | None, str]:
    result, postponed = listing["Sales Results"], mdy(listing["Sale Postponed to:"])
    if result in BUYERS:
        bid = f" for {listing['Winning Bid']}" if listing["Winning Bid"] else ""
        return "sold", mdy(listing["Date of Sale"]), f"{result}{bid}"
    if postponed:
        return "scheduled", postponed, f"postponed to {postponed:%m/%d/%Y}"
    return "sold_or_cancelled_unverified", mdy(listing["Date of Sale"]), "sale date passed; no result in the STOX report"


def to_sale(listing: dict) -> tuple[str, str, Sale]:
    state = STATES.get(listing["State"], listing["State"])
    county = re.sub(r"\s*\([A-Z]{2}\)$", "", listing["County"])
    street, city, zip_code = split_address(listing["Property Address"])
    status, sale_date, raw_status = status_of(listing)
    sale = Sale(case=listing["STOX#"], street=street, city=city, zip_code=zip_code, sale_date=sale_date,
                status=status, raw={field: listing[field] for field in KEPT_FIELDS}, raw_status=raw_status,
                upset=money(listing["Opening Bid"]), result=listing["Sales Results"] or None)
    return state, county, sale


def details(listing: dict) -> str:
    lines = [f"Non-judicial trustee sale posted by STOX Posting and Publishing. Trustee: {listing['Trustee']}.",
             f"Originally set for {mdy(listing['Date of Sale']):%B %-d, %Y}."]
    if listing["Sale Postponed to:"]:
        lines.append(f"Postponed to {mdy(listing['Sale Postponed to:']):%B %-d, %Y}.")
    if listing["Sales Results"]:
        lines.append(f"Result: {listing['Sales Results']}"
                     + (f", winning bid {listing['Winning Bid']}." if listing["Winning Bid"] else "."))
    if listing["Opening Bid"]:
        lines.append(f"Opening bid: {listing['Opening Bid']} (set by the trustee).")
    lines.append(f"Property address as posted: {listing['Property Address']}")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, default=INPUT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--stox-consent", action="store_true",
                        help="STOX has given written consent to use its listings; required for non-local databases")
    args = parser.parse_args(argv)
    export = json.loads(args.input.read_text())
    groups: dict[tuple[str, str], list[tuple[dict, Sale]]] = {}
    unusable = []
    for listing in export["listings"]:
        state, county, sale = to_sale(listing)
        if usable_address(sale):
            groups.setdefault((state, county), []).append((listing, sale))
        else:
            unusable.append(listing["STOX#"])
    if args.dry_run:
        sample = [vars(sale) for group in groups.values() for _, sale in group][:3]
        print(json.dumps({"listings": len(export["listings"]), "counties": len(groups), "without_address": unusable,
                          "sample": sample}, indent=2, default=str))
        return 0
    if engine.url.host not in LOCAL_HOSTS and not args.stox_consent:
        raise SystemExit(f"Refusing to load STOX listings into {engine.url.host} without --stox-consent"
                         " (STOX terms section 13: no commercial use without their written consent).")

    report = {"created": 0, "updated": 0, "skipped": len(unusable), "without_address": unusable}
    now = datetime.now(timezone.utc)
    for (state, county), pairs in sorted(groups.items()):
        # complete=False: one day's report is not a county's full list of upcoming sales.
        counts = load_sales(state, county, SOURCE_SYSTEM, export["report_url"], [sale for _, sale in pairs],
                            "stox_trustee_sales", complete=False)
        report["created"] += counts["created"]
        report["updated"] += counts["updated"]
        with engine.begin() as connection:
            for listing, sale in pairs:
                sale_id = connection.execute(text("""UPDATE sheriff_sales SET description_text=:details,
                    sold_amount=:sold_amount, sold_buyer=:buyer, sold_on=:sold_on, sold_raw_status=:sold_raw
                    WHERE state=:state AND county=:county AND source_system=:source AND sheriff_number=:number
                    RETURNING id"""),
                    {"details": details(listing), "state": state, "county": county, "source": SOURCE_SYSTEM,
                     "number": sale.case, "sold_amount": money(listing["Winning Bid"]) if sale.status == "sold" else None,
                     "buyer": BUYERS.get(listing["Sales Results"]),
                     "sold_on": sale.sale_date if sale.status == "sold" else None,
                     "sold_raw": sale.raw_status if sale.status == "sold" else None}).scalar_one()
                if sale.status == "scheduled":
                    # The date it was postponed from, kept in the status history.
                    original = mdy(listing["Date of Sale"])
                    connection.execute(text("""INSERT INTO sheriff_sale_status_history(id,sheriff_sale_id,status,
                        sale_date,observed_at,source_url,raw_status)
                        SELECT :id,:sale_id,'adjourned',:sale_date,:now,:url,:raw
                        WHERE NOT EXISTS(SELECT 1 FROM sheriff_sale_status_history WHERE sheriff_sale_id=:sale_id
                          AND status='adjourned' AND sale_date=:sale_date)"""),
                        {"id": str(uuid.uuid4()), "sale_id": sale_id, "sale_date": original, "now": now,
                         "url": export["report_url"], "raw": sale.raw_status})
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
