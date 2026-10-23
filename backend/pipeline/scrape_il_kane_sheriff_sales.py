"""Kane County, IL sheriff's foreclosure sales from the Sheriff's posted list.

The Kane County Sheriff posts its foreclosure sales list as a PDF with a text layer
(applications.kanecountyil.gov/foreclosures/foreclosures.pdf, "AS POSTED <date>"): sale
date, chancery number, sheriff's number, property address with the town, and judgment
amount. No party names. The town is the address's last words, split off with the list
of Kane County municipalities; ZIPs come later from the Census geocoder (fill_missing_zips).

    python -m pipeline.scrape_il_kane_sheriff_sales
    python -m pipeline.load_il_county_sheriff_sales --county Kane
"""
import argparse
import io
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

from pypdf import PdfReader

from pipeline.scraping.config import ScrapingSettings
from pipeline.scraping.http import PoliteClient

URL = "https://applications.kanecountyil.gov/foreclosures/foreclosures.pdf"
OUTPUT = Path("data/sheriff_sales/il_kane_sheriff_sales.json")
PARSER_VERSION = "il_kane_sheriff_foreclosures_v1"
ROW = re.compile(r"(\d{1,2}/\d{1,2}/\d{4})\s+(\S+)\s+(\d{2}SCH\d+)\s+(.+?)\s+([\d,]+\.\d{2})(?=\s|$)")
# Longest first, so "South Elgin" wins over "Elgin" and "North Aurora" over "Aurora".
TOWNS = sorted([
    "Algonquin", "Aurora", "North Aurora", "Barrington Hills", "Bartlett", "Batavia", "Big Rock", "Burlington",
    "Campton Hills", "Carpentersville", "East Dundee", "West Dundee", "Elburn", "Elgin", "South Elgin", "Geneva",
    "Gilberts", "Hampshire", "Hoffman Estates", "Huntley", "Kaneville", "Lily Lake", "Maple Park", "Montgomery",
    "Pingree Grove", "Plato Center", "Sleepy Hollow", "St Charles", "Saint Charles", "Streamwood", "Sugar Grove",
    "Virgil", "Wayne"], key=len, reverse=True)


def split_town(address: str) -> tuple[str, str | None]:
    """'278 B WHITFIELD DR Sugar Grove' -> ('278 B WHITFIELD DR', 'Sugar Grove')."""
    value = " ".join(address.split())
    canonical = re.sub(r"\bSt\.?\s+Charles$", "St Charles", value, flags=re.I)
    for town in TOWNS:
        if re.search(rf"\s{re.escape(town)}$", canonical, re.I):
            street = canonical[:-len(town)].strip(" ,")
            return street, "St. Charles" if town in ("St Charles", "Saint Charles") else town
    return value, None


def sales_from(text: str, today: date) -> list[dict]:
    sales = {}
    for sale_date, chancery, sheriff_number, address, judgment in ROW.findall(" ".join(text.split())):
        when = datetime.strptime(sale_date, "%m/%d/%Y").date()
        if when < today:
            continue
        street, town = split_town(address)
        sales[sheriff_number] = {"sheriff_number": sheriff_number, "chancery_number": chancery,
                                 "sale_date": when.isoformat(), "street": street, "city": town,
                                 "address_as_listed": " ".join(address.split()),
                                 "judgment": float(judgment.replace(",", ""))}
    return sorted(sales.values(), key=lambda sale: (sale["sale_date"], sale["sheriff_number"]))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    with PoliteClient(ScrapingSettings.from_env()) as client:
        response = client.get(URL)
        response.raise_for_status()
    text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(response.content)).pages)
    if "Foreclosure Sales" not in text:
        raise SystemExit(f"Kane County list not recognised at {URL}; previous snapshot kept")
    posted = re.search(r"AS POSTED\s+(\d{1,2}/\d{1,2}/\d{4})", text)
    sales = sales_from(text, date.today())
    snapshot = {"source_system": "il_county_sheriff_sale", "state": "IL", "county": "Kane", "source_url": URL,
                "posted": posted.group(1) if posted else None, "scraped_at": datetime.now(timezone.utc).isoformat(),
                "parser_version": PARSER_VERSION, "sales": sales}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, indent=1) + "\n")
    print(f"Kane: {len(sales)} upcoming sales ({sum(1 for s in sales if not s['city'])} without a town) -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
