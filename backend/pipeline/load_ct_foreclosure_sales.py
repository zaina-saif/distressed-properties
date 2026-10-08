"""Load the Connecticut foreclosure-by-sale snapshot (see scrape_ct_foreclosure_sales).

    python -m pipeline.load_ct_foreclosure_sales
"""
import json
import re
from collections import defaultdict
from datetime import date, datetime

from pipeline.ct_towns import CT_TOWN_COUNTY, county_for
from pipeline.sale_listing_loader import Sale, load_sales
from pipeline.scrape_ct_foreclosure_sales import OUTPUT

SOURCE_SYSTEM = "ct_court_foreclosure_sale"


def address(listing, town):
    """Street, city and ZIP from "... ADDRESS: 65-73 Center Street Bridgeport, CT 06604"."""
    text = listing.split("ADDRESS:", 1)[1] if "ADDRESS:" in listing else listing.split("SALE:", 1)[-1]
    # Drop lead-in words such as "Residential property" before the house number.
    text = re.sub(r"^\s*(?:(?:residential|commercial|vacant|land|property|premises|known as|located at)\b[\s:,]*)+",
                  "", text, flags=re.I)
    match = re.search(r"^(.*?),?\s*CT\.?\s*(\d{5})?\b", text.strip(), re.I)
    before, zip_code = (match.group(1), match.group(2)) if match else (text, None)
    before = before.strip(" ,")
    city = None
    if town and before.upper().endswith(town.upper()):
        city, before = town, before[: -len(town)]
    elif "," in before:
        before, city = before.rsplit(",", 1)
    # Keep the published street (ranges like "65-73" included); drop "a/k/a" aliases.
    street = re.split(r"\s+(?:a/k/a|aka|f/k/a)\s+", before.strip(" ,"), maxsplit=1, flags=re.I)[0]
    return " ".join(street.split()).strip(" ,"), (city or town or "").strip().title() or None, zip_code


def parties(caption):
    plaintiff, _, defendant = (caption or "").partition(" v. ")
    return " ".join(plaintiff.split()) or None, " ".join(defendant.split()) or None


def sale_status(listing, sale_date, today):
    upper = listing.upper()
    if "CANCEL" in upper:
        return "cancelled"
    if "POSTPON" in upper or "CONTINUED" in upper:
        return "adjourned"
    # Still listed after its sale day: awaiting court approval, sold or cancelled; the list does not say.
    return "scheduled" if sale_date is None or sale_date >= today else "sold_or_cancelled_unverified"


def to_sale(record, today):
    town = (record["notice"].get("TOWN") or record["town"]).strip()
    street, city, zip_code = address(record["listing"], town)
    try:
        sale_date = datetime.strptime(record["sale_date"].split()[0], "%m/%d/%Y").date()
    except (ValueError, IndexError):
        sale_date = None
    if sale_date and sale_date.year > today.year + 2:  # typos such as "2204" on the court's list
        sale_date = None
    plaintiff, defendant = parties(record["notice"].get("Case Caption"))
    kind = re.search(r"SALE:\s*(Residential|Commercial|Land|Condominium|Multi[- ]Family)?", record["listing"], re.I)
    return Sale(case=record["posting_id"], street=street, city=city, zip_code=zip_code, sale_date=sale_date,
                status=sale_status(record["listing"], sale_date, today), raw=record, raw_status=record["listing"][:200],
                plaintiff=plaintiff, defendant=defendant, property_number=record["notice"].get("Docket Number") or record["docket"],
                result=(kind.group(1) if kind and kind.group(1) else "Foreclosure sale"))


def main():
    snapshot = json.loads(OUTPUT.read_text())
    today = date.today()
    by_county = defaultdict(list)
    unknown = 0
    for record in snapshot["records"]:
        town = (record["notice"].get("TOWN") or record["town"]).strip()
        county = county_for(town) or county_for(record["town"])
        if not county:
            unknown += 1
            continue
        by_county[county].append(to_sale(record, today))
    # Every county is loaded, even with no sales, so sales that left the list are retired.
    for county in sorted(set(CT_TOWN_COUNTY.values())):
        print(f"CT {county}: {load_sales('CT', county, SOURCE_SYSTEM, snapshot['source_url'], by_county[county], job=f'ct_court_{county.lower().replace(' ', '_')}')}")
    if unknown:
        print(f"{unknown} sales had a town that is not in the Connecticut town list and were skipped")


if __name__ == "__main__":
    main()
