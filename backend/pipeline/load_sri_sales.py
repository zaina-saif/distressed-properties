"""Load SRI Services snapshots (see scrape_sri) into the operational DB.

    python -m pipeline.load_sri_sales --all
    python -m pipeline.load_sri_sales --all --history   # past results (scrape_sri --history-from)
"""
import argparse
import json
import re
import time
from datetime import date, datetime

from sqlalchemy.exc import OperationalError

from pipeline.sale_listing_loader import Sale, load_sales, money
from pipeline.scrape_sri import OUTPUT, STATE, snapshot_path

SOURCE_SYSTEM = "in_sri_sheriff_sale"


def status(description, sale_date, today):
    """Our status for SRI's sale status ("Sale Active", "Sold To 3rd Party", "Cancelled", ...)."""
    text = (description or "").lower()
    if text.startswith("sold"):
        return "sold"
    if "bankrupt" in text:
        return "bankruptcy"
    if "redeem" in text:
        return "redeemed"
    if re.search(r"postpone|continu|reschedul|reset", text):
        return "adjourned" if sale_date and sale_date >= today else "sold_or_cancelled_unverified"
    if re.search(r"cancel|withdraw|vacat|dismiss|stay", text):
        return "cancelled"
    if sale_date and sale_date >= today:
        return "scheduled"
    # Still "Sale Active" after the sale day: the result is not published yet.
    return "sold_or_cancelled_unverified"


def result_text(description, price):
    """Status history text, with the price for a sale ("Sold To 3rd Party for $69,000.00"),
    which pipeline.sale_results reads."""
    amount = money(price)
    if (description or "").lower().startswith("sold") and amount:
        return f"{description} for ${amount:,.2f}"
    return description


def address(listing):
    """Street, city and 5-digit ZIP. address1 sometimes repeats the city line after a
    line break ("19548 Yoder St\\r\\nSouth Bend, Indiana 46614-5540") or after commas."""
    street = " ".join((listing.get("address1") or "").splitlines()[0].split()) if listing.get("address1") else ""
    # Some counties write the whole address on one line ("1607 Etna Avenue, Huntington, Indiana, 46750").
    street = re.split(r",\s*[^,]*,\s*(?:Indiana|IN)\b", street, maxsplit=1, flags=re.IGNORECASE)[0].strip(" ,")
    city = " ".join((listing.get("city") or "").split()).title() or None
    zip_match = re.match(r"\s*(\d{5})", listing.get("zip") or "")
    return street, city, zip_match.group(1) if zip_match else None


def sale_date(listing):
    try:
        return datetime.strptime(listing.get("auctionDate") or listing.get("date") or "", "%m/%d/%Y").date()
    except ValueError:
        return None


def to_sale(item, today):
    listing, detail = item["listing"], item.get("detail") or {}
    info = detail.get("propertyInfo") or {}
    street, city, zip_code = address(listing)
    when = sale_date(listing)
    description = info.get("status") or listing.get("saleStatusDescription")
    cause = (info.get("causeNumber") or listing.get("displaySaleId") or "").strip()
    parcel = (listing.get("propertyId") or info.get("propertyId") or "").strip() or None
    # One cause number can sell several parcels, so the parcel is part of the key.
    case = f"{cause}:{parcel}" if cause and parcel else cause or parcel
    try:
        latitude, longitude = float(listing["latitude"]), float(listing["longitude"])
    except (KeyError, TypeError, ValueError):
        latitude = longitude = None
    if latitude is not None and not (37 <= latitude <= 42.5 and -88.5 <= longitude <= -84.5):
        latitude = longitude = None  # Outside Indiana: a bad geocode.
    return Sale(
        case=case, street=street, city=city, zip_code=zip_code, sale_date=when,
        status=status(description, when, today), raw=item,
        raw_status=result_text(description, info.get("salePrice")),
        parcel=parcel,
        # "Pending" until the sheriff sets it; the judgment is listed for every case.
        upset=money(info.get("minimumBid")) if re.search(r"\d", info.get("minimumBid") or "") else None,
        judgment=money(info.get("judgementAmount")),
        plaintiff=(info.get("plantiff") or "").strip() or None,
        defendant=(info.get("defendant") or listing.get("briefLegal") or "").strip() or None,
        attorney=(info.get("attorney") or "").strip() or None,
        result=description, property_number=cause or None,
        latitude=latitude, longitude=longitude)


def load(county, history=False):
    snapshot = json.loads(snapshot_path(county, history).read_text())
    today = date.today()
    sales = [to_sale(item, today) for item in snapshot["items"]]
    sales = [sale for sale in sales if sale.case]
    if history:
        # Oldest first, so each case's status history ends with its latest result.
        sales.sort(key=lambda sale: sale.sale_date or date.min)
    else:
        # One row per case: its latest sale date.
        latest = {}
        for sale in sales:
            if sale.case not in latest or (sale.sale_date or date.min) >= (latest[sale.case].sale_date or date.min):
                latest[sale.case] = sale
        sales = list(latest.values())
    return load_sales(STATE, county, SOURCE_SYSTEM, snapshot["source_url"], sales,
                      job=f"in_sri_{county.lower().replace(' ', '_')}{'_history' if history else ''}",
                      complete=not history)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--counties", nargs="+")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--history", action="store_true",
                        help="Load the history/ snapshots of past results; current listings are left as they are")
    args = parser.parse_args()
    folder = OUTPUT / "history" if args.history else OUTPUT
    if args.all:
        counties = sorted(json.loads(path.read_text())["county"] for path in folder.glob(f"{STATE.lower()}_*.json"))
    else:
        counties = args.counties or []
    failed = []
    for county in counties:
        if not snapshot_path(county, args.history).exists():
            print(f"{STATE} {county}: no snapshot, skipped")
            continue
        # Loading is safe to repeat, so a dropped database connection is retried.
        for attempt in range(3):
            try:
                print(f"{STATE} {county}: {load(county, history=args.history)}", flush=True)
                break
            except OperationalError as exc:
                print(f"{STATE} {county}: connection lost (attempt {attempt + 1}): {str(exc).splitlines()[0]}",
                      flush=True)
                time.sleep(10)
        else:
            failed.append(county)
    if failed:
        raise SystemExit(f"Failed counties: {', '.join(failed)}")


if __name__ == "__main__":
    main()
