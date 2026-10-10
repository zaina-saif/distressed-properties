"""Load RealAuction snapshots (see scrape_realauction) into the operational DB.

    python -m pipeline.load_realauction_sales --state OH --all
    python -m pipeline.load_realauction_sales --state FL --all --history   # past results (scrape --history-from)
"""
import argparse
import json
import re
import time
from datetime import date

from sqlalchemy.exc import OperationalError

from pipeline import colorado_addresses
from pipeline.sale_listing_loader import Sale, load_sales, money
from pipeline.scrape_realauction import SOURCES, snapshot_path

SOURCE_SYSTEM = {"OH": "oh_realauction_sheriff_sale", "FL": "fl_realforeclose_clerk_sale",
                 "CO": "co_realforeclose_public_trustee_sale", "TX": "tx_realauction_tax_sale"}


def address(fields, state):
    """Street, city and 5-digit ZIP from "Property Address" and its unlabelled second line
    ("CLEVELAND , 441050000" in Ohio, "HIALEAH, FL- 33015" in Florida)."""
    street = " ".join((fields.get("Property Address") or "").split())
    # Texas adds ZIP+4 ("DALLAS, TX 75216-5234").
    second = re.sub(r"(\d{5})-\d{4}\s*$", r"\1", fields.get("Property Address 2") or "")
    match = re.match(rf"\s*(.*?)\s*,?\s*(?:{state}\b)?\s*[,-]?\s*(\d{{5}})?\d*\s*$", second, re.I)
    city = match.group(1).strip(" ,-") if match else second.strip()
    return street, city or None, match.group(2) if match else None


def result_status(result):
    """Our status for a closed auction's published result, or None when it has none."""
    if not result or not result.get("status"):
        return None
    text = result["status"].lower()
    if text == "auction sold":
        # Ohio shows "Auction Sold" with "Unsold" when nobody bid the opening price.
        return "sold" if result.get("sold_to") else "unsold"
    if "bankrupt" in text:
        return "bankruptcy"
    if "redeem" in text:
        return "redeemed"
    if "postpone" in text or "reset" in text or "continued" in text:
        return "adjourned"
    if re.search(r"cancel|withdrawn|vacated|dismissed|stayed", text):
        return "cancelled"
    return None


def result_text(item):
    """Status history text: the published result, with the amount and buyer for a sale
    ("Auction Sold to 3rd Party Bidder for $69,000.00"), which pipeline.sale_results reads."""
    result = item.get("result") or {}
    if result.get("status") == "Auction Sold":
        if result.get("sold_to"):
            return f"Auction Sold to {result['sold_to']} for {result.get('amount') or 'an unpublished amount'}"
        return f"Auction closed unsold at {result.get('amount') or 'the opening bid'}"
    return result.get("status")


def status(item, today):
    if item["area"] == "W":
        return "scheduled"
    published = result_status(item.get("result"))
    if published:
        return published
    # "Closed or canceled" before the sale day can only be a cancellation; on or
    # after it, without a published result, we cannot tell whether it sold.
    return "cancelled" if date.fromisoformat(item["sale_date"]) > today else "sold_or_cancelled_unverified"


def case_number(fields):
    """Ohio adds the sheriff's number in brackets: "CV11762673 (66355)"; Texas adds the
    constable precinct: "TX-24-01693 (8)"."""
    raw = fields.get("Case #") or fields.get("Cause Number") or ""
    match = re.match(r"\s*(.*?)\s*(?:\((\d+)\))?\s*$", raw)
    return (match.group(1) or raw.strip()), (match.group(2) if match else None)


def current_items(items, today):
    """One item per case: the latest sale day, preferring a scheduled listing on ties."""
    best = {}
    for item in items:
        case, _ = case_number(item["fields"])
        if not case:
            continue
        # One Texas tax suit can sell several tracts, so key by the appraisal account too.
        if item["fields"].get("Account Number"):
            case = f"{case}:{item['fields']['Account Number'].strip()}"
        key = (item["sale_date"], item["area"] == "W")
        if case not in best or key > (best[case]["sale_date"], best[case]["area"] == "W"):
            best[case] = item
    return best


def history_items(items):
    """Every past auction in date order, so each case's status history is complete and
    its latest result is written last."""
    keyed = []
    for item in items:
        case, _ = case_number(item["fields"])
        if not case:
            continue
        if item["fields"].get("Account Number"):
            case = f"{case}:{item['fields']['Account Number'].strip()}"
        keyed.append((case, item))
    return sorted(keyed, key=lambda pair: (pair[1]["sale_date"], pair[1]["area"] == "W"))


def load(state, county, history=False):
    snapshot = json.loads(snapshot_path(state, county, history=history).read_text())
    sales = []
    entries = history_items(snapshot["items"]) if history else current_items(snapshot["items"], date.today()).items()
    for case, item in entries:
        fields = item["fields"]
        street, city, zip_code = address(fields, state)
        raw = {**item, "source_url": snapshot["source_url"], "parser_version": snapshot["parser_version"]}
        if state == "CO" and street and not city:
            # Colorado sites often give only the street; fill city and ZIP from the
            # state's address points when the match is unambiguous.
            found = colorado_addresses.city_and_zip(street, county)
            if found:
                city, zip_code = found
                raw["address_completed_from"] = colorado_addresses.SOURCE
        _, sheriff_number = case_number(fields)
        area = "waiting" if item["area"] == "W" else "closed or canceled"
        sales.append(Sale(
            case=case, street=street, city=city, zip_code=zip_code,
            sale_date=date.fromisoformat(item["sale_date"]), status=status(item, date.today()),
            raw=raw,
            raw_status=f"{result_text(item) or area} (auction {item['auction_id']})",
            parcel=(fields.get("Parcel ID") or fields.get("Account Number") or "").strip() or None,
            # Ohio's opening bid is the minimum bid (two-thirds of the appraisal);
            # Florida lists the final judgment and no opening bid.
            # Colorado sites show a placeholder "Final Judgment Amount" ($300.00 on every
            # El Paso sale) and hide the lender's bid, so no amount is taken there.
            # Texas lists the court's adjudged value (kept in the raw payload, it is
            # not a judgment) and an estimated minimum bid: the taxes, costs and
            # fees owed, which is the opening bid at a tax sale.
            upset=money(fields.get("Opening Bid") or fields.get("Est. Min. Bid")),
            judgment=None if state == "CO" else money(fields.get("Final Judgment Amount")),
            result=fields.get("Case Status") or fields.get("Auction Type"), property_number=sheriff_number))
    return load_sales(state, county, SOURCE_SYSTEM[state], snapshot["source_url"], sales,
                      job=f"{state.lower()}_realauction_{county.lower()}{'_history' if history else ''}",
                      complete=not history)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--state", required=True, choices=sorted(SOURCES))
    parser.add_argument("--counties", nargs="+")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--history", action="store_true",
                        help="Load the history/ snapshots of past results; current listings are left as they are")
    args = parser.parse_args()
    counties = sorted(SOURCES[args.state]) if args.all else args.counties or []
    failed = []
    for county in counties:
        if not snapshot_path(args.state, county, history=args.history).exists():
            print(f"{args.state} {county}: no snapshot, skipped")
            continue
        # Loading is safe to repeat, so a dropped database connection is retried.
        for attempt in range(3):
            try:
                print(f"{args.state} {county}: {load(args.state, county, history=args.history)}", flush=True)
                break
            except OperationalError as exc:
                print(f"{args.state} {county}: connection lost (attempt {attempt + 1}): {str(exc).splitlines()[0]}",
                      flush=True)
                time.sleep(10)
        else:
            failed.append(county)
    if failed:
        raise SystemExit(f"Failed counties: {', '.join(failed)}")


if __name__ == "__main__":
    main()
