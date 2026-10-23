"""Tarrant County, TX constable's tax foreclosure sales (first Tuesday of the month).

Tarrant County's delinquent-tax sales are run by Constable Precinct 3, which posts one page
per sale month (tarrantcountytx.gov .../monthly-tax-sales-listings/november-3--2026.html;
robots.txt asks for a 30-second crawl delay, which PoliteClient honours): for each law firm
(Perdue Brandon, Linebarger, ...) a table of cause number, account number and status
("For Sale", "Withdrawn", "For Sale Royalty Interest only"). There are no addresses and
no bids.

Each account's situs address and city come from the Tarrant Appraisal District's certified
property data (tad.org data downloads, PropertyData(Delimited).ZIP, refreshed when a week
old in .local/tad/): only the account number, situs address and city code are read, never
the owner fields. City codes are TAD's taxing-unit numbers (026 Fort Worth, 024 Arlington,
...); unincorporated accounts and unknown codes get no city and are reported. ZIPs and
positions come from fill_missing_zips. Mineral and royalty interests are left out.

    python -m pipeline.scrape_tx_tarrant_tax_sales
    python -m pipeline.load_tx_tarrant_tax_sales
"""
import argparse
import html
import io
import json
import re
import time
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

from pipeline.scraping.config import ScrapingSettings
from pipeline.scraping.http import PoliteClient

BASE = "https://www.tarrantcountytx.gov"
INDEX = f"{BASE}/en/constables/constable-3/delinquent-tax-sales/monthly-tax-sales-listings.html"
TAD_URL = "https://www.tad.org/content/data-download/PropertyData(Delimited).ZIP"
TAD_CACHE = Path(__file__).resolve().parents[2] / ".local" / "tad" / "pd.zip"
OUTPUT = Path("data/sheriff_sales/tx_tarrant_tax_sales.json")
PARSER_VERSION = "tx_tarrant_constable3_tax_sales_v1"
MONTH_PAGE = re.compile(r'href="(/en/constables/constable-3/delinquent-tax-sales/monthly-tax-sales-listings/'
                        r'([a-z]+)-(\d{1,2})--(\d{4})\.html)"')
ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S)
# TAD taxing-unit codes of the cities (2025 tax rate sheet).
CITIES = {
    "001": "Azle", "002": "Bedford", "003": "Benbrook", "004": "Blue Mound", "005": "Colleyville", "006": "Crowley",
    "008": "Edgecliff Village", "009": "Everman", "010": "Forest Hill", "011": "Grapevine", "013": "Keller",
    "014": "Kennedale", "015": "Lakeside", "016": "Lake Worth", "017": "Mansfield", "018": "North Richland Hills",
    "019": "Pantego", "020": "Richland Hills", "021": "Saginaw", "022": "Southlake", "023": "Westover Hills",
    "024": "Arlington", "025": "Euless", "026": "Fort Worth", "028": "Hurst", "029": "River Oaks",
    "030": "White Settlement", "031": "Watauga", "032": "Westworth Village", "033": "Burleson", "034": "Haslet",
    "036": "Pelican Bay", "037": "Westlake", "038": "Grand Prairie", "039": "Sansom Park", "040": "Newark",
    "041": "Reno", "042": "Flower Mound", "043": "Roanoke", "044": "Trophy Club"}
TAD_COLUMNS = {"account": "Account_Num", "situs": "Situs_Address", "city": "City"}


def month_pages(index: str, today: date) -> list[tuple[str, date]]:
    pages = {}
    for path, month, day, year in MONTH_PAGE.findall(index):
        sale_day = datetime.strptime(f"{month} {day} {year}", "%B %d %Y").date()
        if sale_day >= today:
            pages[path] = sale_day
    return sorted(pages.items(), key=lambda item: item[1])


def accounts_from(page: str) -> list[dict]:
    """Rows on a month's page that are for sale, without mineral and royalty interests."""
    found = []
    for row in ROW.findall(page):
        cells = [" ".join(html.unescape(re.sub(r"<[^>]+>", " ", cell)).split()) for cell in CELL.findall(row)]
        if len(cells) < 3 or not re.fullmatch(r"\d{5,9}", cells[1]):
            continue
        status = cells[2]
        if not status.lower().startswith("for sale") or re.search(r"(?i)royalty|mineral|interest only", status):
            continue
        found.append({"cause": cells[0], "account": cells[1], "status": status})
    return found


def tad_places(path: Path, accounts: set[str]) -> dict[str, dict]:
    """Situs address and city per account (leading zeros dropped), read column by name."""
    wanted = {account.lstrip("0") for account in accounts}
    found: dict[str, dict] = {}
    with zipfile.ZipFile(path) as archive, archive.open(archive.namelist()[0]) as raw:
        lines = io.TextIOWrapper(raw, encoding="latin-1")
        header = next(lines).rstrip("\r\n").split("|")
        position = {key: header.index(name) for key, name in TAD_COLUMNS.items()}
        for line in lines:
            fields = line.rstrip("\r\n").split("|")
            account = fields[position["account"]].strip().lstrip("0")
            if account in wanted and account not in found and fields[position["situs"]].strip():
                code = fields[position["city"]].strip()
                found[account] = {"street": " ".join(fields[position["situs"]].split()), "city_code": code or None,
                                  "city": CITIES.get(code)}
    return found


def tad_file(client: PoliteClient) -> Path:
    if not TAD_CACHE.exists() or time.time() - TAD_CACHE.stat().st_mtime > 7 * 86400:
        response = client.get(TAD_URL, timeout=600)
        response.raise_for_status()
        TAD_CACHE.parent.mkdir(parents=True, exist_ok=True)
        TAD_CACHE.write_bytes(response.content)
    return TAD_CACHE


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    rows = []
    with PoliteClient(ScrapingSettings.from_env()) as client:
        index = client.get(INDEX)
        index.raise_for_status()
        for path, sale_day in month_pages(index.text, date.today()):
            page = client.get(BASE + path)
            page.raise_for_status()
            rows += [{**row, "sale_date": sale_day.isoformat(), "list_url": BASE + path}
                     for row in accounts_from(page.text)]
        places = tad_places(tad_file(client), {row["account"] for row in rows}) if rows else {}
    sales, unplaced = {}, []
    for row in rows:
        place = places.get(row["account"].lstrip("0"))
        if not place or not place["city"]:
            unplaced.append(f"{row['account']} ({place['street'] + ', city code ' + str(place['city_code']) if place else 'not in TAD data'})")
            continue
        sales[(row["account"], row["sale_date"])] = {**row, "street": place["street"], "city": place["city"]}
    snapshot = {"source_system": "tx_tarrant_constable_tax_sale", "state": "TX", "county": "Tarrant", "source_url": INDEX,
                "scraped_at": datetime.now(timezone.utc).isoformat(), "parser_version": PARSER_VERSION,
                "sales": sorted(sales.values(), key=lambda sale: (sale["sale_date"], sale["account"])), "unplaced": unplaced}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, indent=1) + "\n")
    print(f"Tarrant: {len(rows)} for sale, {len(sales)} placed, {len(unplaced)} without a city -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
