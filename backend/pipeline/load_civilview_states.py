"""Load CivilView snapshots for counties outside New Jersey (see scrape_civilview_states).

    python -m pipeline.load_civilview_states --all
"""
import argparse
import json
import re

from pipeline.adapters.civilview_listing import parse_date
from pipeline.sale_listing_loader import Sale, load_sales, money
from pipeline.scrape_civilview_states import COUNTIES, key, snapshot_path

SOURCE_SYSTEM = "civilview_sheriff_sale"


def first(fields, *labels):
    for label in labels:
        values = fields.get(label)
        if values:
            return " ".join(values).strip() or None
    return None


def normalize_status(raw):
    value = (raw or "").lower()
    for needle, status in (("scheduled", "scheduled"), ("bankrupt", "bankruptcy"), ("postpon", "adjourned"),
                           ("continu", "adjourned"), ("adjourn", "adjourned"), ("cancel", "cancelled"),
                           ("withdr", "cancelled"), ("stay", "stayed"), ("redeem", "redeemed"), ("sold", "sold")):
        if needle in value:
            return status
    return value.replace(" ", "_") or "scheduled"


def address(fields, state):
    """Street and "CITY ST ZIP" lines from the Address or Property Address field."""
    lines = fields.get("Property Address") or fields.get("Address") or []
    # New Castle flags some listings with a leading "*"; the raw record keeps it.
    street = " ".join(lines[0].lstrip("*").split()) if lines else ""
    for line in lines[1:]:
        match = re.match(rf"\s*(.+?)\s*,?\s+{state}\s+(\d{{5}})?", line, re.I)
        if match:
            return street, match.group(1).strip().title(), match.group(2)
    return street, None, None


def to_sale(record, state):
    fields = record["fields"]
    history = record["status_history"]
    sheriff_number = first(fields, "Sheriff #") or record["detail_url"].rsplit("=", 1)[-1]
    # Texas counties combine several precincts whose numbers can collide.
    case = f"{record['county_id']}:{sheriff_number}" if state == "TX" else sheriff_number
    street, city, zip_code = address(fields, state)
    raw_status = history[0]["status"] if history else None
    return Sale(
        case=case, street=street, city=city, zip_code=zip_code,
        sale_date=parse_date(first(fields, "Sales Date")), status=normalize_status(raw_status) if raw_status else "scheduled",
        raw=record, raw_status=raw_status, parcel=first(fields, "Parcel #", "OPA #", "Parcel"),
        # "$0.00" is the portal's placeholder for an amount not yet posted.
        upset=money(first(fields, "Minimum Bid", "Approx. Upset", "Upset")) or None,
        judgment=money(first(fields, "Approx. Judgment", "Debt Amount", "Judgment")) or None,
        plaintiff=first(fields, "Plaintiff"), defendant=first(fields, "Defendant"),
        attorney=first(fields, "Attorney"), result=first(fields, "Sale Type"),
        property_number=first(fields, "Court Case #"))


def load(state, county):
    snapshot = json.loads(snapshot_path(state, county).read_text())
    sales = [to_sale(record, state) for record in snapshot["records"]]
    return load_sales(state, county, SOURCE_SYSTEM, snapshot["source_urls"][0], sales,
                      job=f"{state.lower()}_civilview_{county.lower().replace(' ', '_')}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--counties", nargs="+", choices=sorted(key(*item) for item in COUNTIES))
    parser.add_argument("--state")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    if args.all:
        targets = sorted(COUNTIES)
    elif args.state:
        targets = sorted(item for item in COUNTIES if item[0] == args.state.upper())
    else:
        targets = [tuple(value.split(":", 1)) for value in args.counties or []]
    for state, county in targets:
        if not snapshot_path(state, county).exists():
            print(f"{state} {county}: no snapshot, skipped")
            continue
        print(f"{state} {county}: {load(state, county)}", flush=True)


if __name__ == "__main__":
    main()
