"""Load RealAuction snapshots (see scrape_realauction) into the operational DB.

    python -m pipeline.load_realauction_sales --state OH --all
"""
import argparse
import json
import re
from datetime import date

from pipeline import colorado_addresses
from pipeline.sale_listing_loader import Sale, load_sales, money
from pipeline.scrape_realauction import SOURCES, snapshot_path

SOURCE_SYSTEM = {"OH": "oh_realauction_sheriff_sale", "FL": "fl_realforeclose_clerk_sale",
                 "CO": "co_realforeclose_public_trustee_sale"}


def address(fields, state):
    """Street, city and 5-digit ZIP from "Property Address" and its unlabelled second line
    ("CLEVELAND , 441050000" in Ohio, "HIALEAH, FL- 33015" in Florida)."""
    street = " ".join((fields.get("Property Address") or "").split())
    second = fields.get("Property Address 2") or ""
    match = re.match(rf"\s*(.*?)\s*,?\s*(?:{state}\b)?\s*[,-]?\s*(\d{{5}})?\d*\s*$", second, re.I)
    city = match.group(1).strip(" ,-") if match else second.strip()
    return street, city or None, match.group(2) if match else None


def status(item, today):
    if item["area"] == "W":
        return "scheduled"
    # "Closed or canceled" before the sale day can only be a cancellation; on or
    # after it the site does not say whether the property sold.
    return "cancelled" if date.fromisoformat(item["sale_date"]) > today else "sold_or_cancelled_unverified"


def case_number(fields):
    """Ohio adds the sheriff's number in brackets: "CV11762673 (66355)"."""
    raw = fields.get("Case #") or ""
    match = re.match(r"\s*(.*?)\s*(?:\((\d+)\))?\s*$", raw)
    return (match.group(1) or raw.strip()), (match.group(2) if match else None)


def current_items(items, today):
    """One item per case: the latest sale day, preferring a scheduled listing on ties."""
    best = {}
    for item in items:
        case, _ = case_number(item["fields"])
        if not case:
            continue
        key = (item["sale_date"], item["area"] == "W")
        if case not in best or key > (best[case]["sale_date"], best[case]["area"] == "W"):
            best[case] = item
    return best


def load(state, county):
    snapshot = json.loads(snapshot_path(state, county).read_text())
    sales = []
    for case, item in current_items(snapshot["items"], date.today()).items():
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
            raw_status=f"{area} (auction {item['auction_id']})",
            parcel=(fields.get("Parcel ID") or "").strip() or None,
            # Ohio's opening bid is the minimum bid (two-thirds of the appraisal);
            # Florida lists the final judgment and no opening bid.
            # Colorado sites show a placeholder "Final Judgment Amount" ($300.00 on every
            # El Paso sale) and hide the lender's bid, so no amount is taken there.
            upset=money(fields.get("Opening Bid")),
            judgment=None if state == "CO" else money(fields.get("Final Judgment Amount")),
            result=fields.get("Case Status") or fields.get("Auction Type"), property_number=sheriff_number))
    return load_sales(state, county, SOURCE_SYSTEM[state], snapshot["source_url"], sales,
                      job=f"{state.lower()}_realauction_{county.lower()}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--state", required=True, choices=sorted(SOURCES))
    parser.add_argument("--counties", nargs="+")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    counties = sorted(SOURCES[args.state]) if args.all else args.counties or []
    for county in counties:
        if not snapshot_path(args.state, county).exists():
            print(f"{args.state} {county}: no snapshot, skipped")
            continue
        print(f"{args.state} {county}: {load(args.state, county)}", flush=True)


if __name__ == "__main__":
    main()
