"""North Carolina foreclosure sales from the Hutchens Law Firm's pending sales list.

North Carolina mortgage foreclosures are mostly power-of-sale foreclosures: after a
hearing before the Clerk of Superior Court, a substitute trustee sells the property at
the courthouse, and the sale stays open for ten days of upset bids. There is no
statewide list. Hutchens Law Firm, one of the state's largest foreclosure firms, publishes
its pending North Carolina sales on one public page (sales.hutchenslawfirm.com,
"This information is free and public"; no robots.txt, no CAPTCHA): file number, special
proceeding (SP) number, county, sale date, property address, deed of trust book/page and,
from the day before the sale, the lender's opening bid. No party names are listed.

Sales whose date passed more than STALE_DAYS ago are left out: the list keeps some
long-postponed files with their original date.

    python -m pipeline.scrape_nc_hutchens_sales
    python -m pipeline.load_nc_hutchens_sales
"""
import argparse
import html
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from pipeline.scraping.config import ScrapingSettings
from pipeline.scraping.http import PoliteClient

URL = "https://sales.hutchenslawfirm.com/NCfcSalesList.aspx"
OUTPUT = Path("data/sheriff_sales/nc_hutchens_foreclosure_sales.json")
PARSER_VERSION = "nc_hutchens_sales_list_v1"
STALE_DAYS = 60
COLUMNS = ["case", "sp_number", "county", "sale_date", "street", "city_state_zip", "deed_of_trust", "bid"]
ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
CSZ = re.compile(r"^(.+?),\s*NC\s*(\d{5})?")


def rows(page: str) -> list[list[str]]:
    """The grid's data rows: eight cells, the fourth a date."""
    found = []
    for row in ROW.findall(page):
        cells = [" ".join(html.unescape(re.sub(r"<[^>]+>", " ", cell)).split()) for cell in CELL.findall(row)]
        if len(cells) == len(COLUMNS) and re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", cells[3]):
            found.append(cells)
    return found


def sales_from(page: str, today: date) -> list[dict]:
    sales = {}
    for cells in rows(page):
        row = dict(zip(COLUMNS, cells))
        sale_date = datetime.strptime(row["sale_date"], "%m/%d/%Y").date()
        if sale_date < today - timedelta(days=STALE_DAYS):
            continue
        city = CSZ.match(row["city_state_zip"])
        sales[row["case"]] = {
            "case": row["case"], "sp_number": row["sp_number"] or None,
            "county": re.sub(r",\s*NC$", "", row["county"]).strip(), "sale_date": sale_date.isoformat(),
            "street": row["street"] or None, "city": city.group(1).strip().title() if city else None,
            "zip_code": city.group(2) if city else None, "deed_of_trust": row["deed_of_trust"] or None,
            "opening_bid": row["bid"] if row["bid"].startswith("$") else None,
        }
    return sorted(sales.values(), key=lambda sale: (sale["county"], sale["sale_date"], sale["case"]))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc)
    with PoliteClient(ScrapingSettings.from_env()) as client:
        response = client.get(URL)
        response.raise_for_status()
    listed = len(rows(response.text))
    sales = sales_from(response.text, now.date())
    if not listed:
        raise SystemExit(f"No sales found on {URL}; the page layout may have changed. Previous snapshot kept.")
    snapshot = {"source_system": "nc_hutchens_foreclosure_sale", "state": "NC", "source_url": URL,
                "scraped_at": now.isoformat(), "parser_version": PARSER_VERSION, "listed": listed, "sales": sales}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, indent=1) + "\n")
    print(f"North Carolina (Hutchens): {listed} listed, {len(sales)} kept, "
          f"{len({sale['county'] for sale in sales})} counties -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
