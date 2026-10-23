"""Will County, IL sheriff's foreclosure sales from the Sheriff's upcoming-sales list.

The Will County Sheriff lists upcoming foreclosure sales on its site
(willcosheriff.org/foreclosures/index.php/upcoming-sales, a Joomla Fabrik list; limit5=0
shows every row on one page): case number, street, city, sale date and opening bid. No
party names. robots.txt is a 404 (no restrictions). ZIPs come from fill_missing_zips.

    python -m pipeline.scrape_il_will_sheriff_sales
    python -m pipeline.load_il_county_sheriff_sales --county Will
"""
import argparse
import html
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

from pipeline.scraping.config import ScrapingSettings
from pipeline.scraping.http import PoliteClient

URL = "https://www.willcosheriff.org/foreclosures/index.php/upcoming-sales"
OUTPUT = Path("data/sheriff_sales/il_will_sheriff_sales.json")
PARSER_VERSION = "il_will_sheriff_upcoming_v1"
ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)


def sales_from(page: str, today: date) -> list[dict]:
    sales = {}
    for row in ROW.findall(page):
        cells = [" ".join(html.unescape(re.sub(r"<[^>]+>", " ", cell)).split()) for cell in CELL.findall(row)]
        if len(cells) < 5 or not re.fullmatch(r"\d{2}-\d{2}-\d{4}", cells[3]):
            continue
        case, street, city, sale_date, bid = cells[:5]
        when = datetime.strptime(sale_date, "%m-%d-%Y").date()
        if when < today:
            continue
        amount = float(bid.replace(",", "")) if re.fullmatch(r"[\d,]+\.\d{2}", bid) else 0.0
        sales[case] = {"sheriff_number": case, "chancery_number": case, "sale_date": when.isoformat(),
                       "street": street, "city": city.title() or None,
                       "opening_bid": amount or None}  # 0.00: not set yet
    return sorted(sales.values(), key=lambda sale: (sale["sale_date"], sale["sheriff_number"]))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    with PoliteClient(ScrapingSettings.from_env()) as client:
        response = client.get(URL, params={"limit5": 0})
        response.raise_for_status()
    if "Common Street Address" not in response.text:
        raise SystemExit(f"Will County list not recognised at {URL}; previous snapshot kept")
    sales = sales_from(response.text, date.today())
    snapshot = {"source_system": "il_county_sheriff_sale", "state": "IL", "county": "Will", "source_url": URL,
                "scraped_at": datetime.now(timezone.utc).isoformat(), "parser_version": PARSER_VERSION, "sales": sales}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, indent=1) + "\n")
    print(f"Will: {len(sales)} upcoming sales -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
