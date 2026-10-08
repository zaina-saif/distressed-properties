"""Load CivilView snapshots for counties outside New Jersey (see scrape_civilview_states).

    python -m pipeline.load_civilview_states --all
"""
import argparse
import json
import re

from pipeline.adapters.civilview_listing import parse_date
from pipeline.apify_scheduled_zillow import STREET_SUFFIX
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


DIRECTION = r"(?:\s+(?:N|S|E|W|NE|NW|SE|SW|NORTH|SOUTH|EAST|WEST)\b)?"


def split_street_city(text):
    """"2116 WASHINGTON AVE CALDWELL" -> street ending at the last street type, then the city."""
    matches = list(re.finditer(STREET_SUFFIX.pattern + DIRECTION, text, re.I))
    if not matches:
        return text.strip(), None
    end = matches[-1].end()
    return text[:end].strip(" ,"), text[end:].strip(" ,") or None


def one_line(text, state):
    """Street, city and ZIP from a single line such as "814 2ND STREET, NEVADA IA 50201"
    or "8739 EDINBURGH ST  NEW ORLEANS LA 70118" (Orleans separates with two spaces)."""
    match = re.search(rf"^(.*?)[\s,]+{state}\s+(\d{{5}})", text.strip(), re.I)
    if not match:
        return text.strip(), None, None
    before, zip_code = match.group(1), match.group(2)
    if "  " in before.strip():
        street, city = re.split(r"\s{2,}", before.strip(), maxsplit=1)
    elif "," in before:
        street, city = before.rsplit(",", 1)
    else:
        street, city = split_street_city(before)
    return street.strip(" ,"), (city or "").strip(" ,").title() or None, zip_code


def address(fields, state):
    """Street, city and ZIP. Counties use a street line plus a "CITY ST ZIP" line, a single
    line, or (Canyon, ID) only a "COMMONLY KNOWN AS ..." phrase in another field."""
    lines = fields.get("Property Address") or fields.get("Address") or fields.get("Address/Description") or []
    if not lines:
        text = " ".join(value for values in fields.values() for value in values)
        known = re.search(rf"COMMONLY KNOWN AS\s*:?\s*(.+?,?\s*{state}\s+\d{{5}})", text, re.I)
        return one_line(known.group(1), state) if known else ("", None, None)
    # New Castle flags some listings with a leading "*"; the raw record keeps it.
    street = " ".join(lines[0].lstrip("*").split())
    city = zip_code = None
    for line in lines[1:]:
        match = re.match(rf"\s*(.+?)\s*,?\s+{state}\s+(\d{{5}})?", line, re.I)
        if match:
            city, zip_code = match.group(1).strip().title(), match.group(2)
            break
    if city is None and len(lines) == 1:
        street, city, zip_code = one_line(street, state)
    # Snohomish writes "SALE FOR REAL PROPERTY LOCATED AT <street> <CITY> WILL BE HELD AT ...".
    located = re.search(r"LOCATED AT\s+(.+?)(?:\s+WILL BE HELD|$)", street, re.I)
    if located:
        street = located.group(1).strip(" ,")
        if city and street.upper().endswith(" " + city.upper()):
            street = street[: -len(city)].strip(" ,")
    return street, city, zip_code


def amount_after(fields, label):
    """A dollar amount written inside a value, e.g. "Writ Amount: $220,143.88" (Louisiana)."""
    for values in fields.values():
        for value in values:
            match = re.search(rf"{label}\s*:?\s*\$\s*([\d,]+(?:\.\d+)?)", value, re.I)
            if match:
                return float(match.group(1).replace(",", ""))
    return None


def to_sale(record, state):
    fields = record["fields"]
    history = record["status_history"]
    sheriff_number = first(fields, "Sheriff #", "Case #") or record["detail_url"].rsplit("=", 1)[-1]
    # Texas counties combine several precincts whose numbers can collide.
    case = f"{record['county_id']}:{sheriff_number}" if state == "TX" else sheriff_number
    street, city, zip_code = address(fields, state)
    raw_status = history[0]["status"] if history else None
    return Sale(
        case=case, street=street, city=city, zip_code=zip_code,
        # Louisiana parishes have no "Sales Date"; the newest status carries the date.
        sale_date=parse_date(first(fields, "Sales Date") or (history[0]["date"] if history else None)), status=normalize_status(raw_status) if raw_status else "scheduled",
        raw=record, raw_status=raw_status, parcel=first(fields, "Parcel #", "OPA #", "Parcel"),
        # "$0.00" is the portal's placeholder for an amount not yet posted.
        upset=money(first(fields, "Minimum Bid", "Approx. Upset", "Upset", "Opening Credit Bid")) or None,
        judgment=money(first(fields, "Approx. Judgment", "Approx. Judgment*", "Debt Amount", "Judgment"))
        or amount_after(fields, "Writ Amount") or None,
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
