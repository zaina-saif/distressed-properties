"""California county tax-defaulted property sales on Bid4Assets.

California counties' treasurer-tax collectors sell property whose taxes have been
unpaid for five years (three for some commercial and vacant land) at a public auction,
most of them online on Bid4Assets, once or twice a year. Bid4Assets' County Tax Sales
calendar (/county-tax-sales) links each sale's storefront; a storefront lists its parcels
in closing groups, which the page reads from /api/storefront/auctions/index (APN,
minimum bid, opening and closing times), and each parcel's auction page gives its
address ("Location: 889 Canada Dr / Milpitas, CA 95035"). No party names are involved.

This collector finds every California storefront on the calendar (timeshare-only sales
are left out), keeps parcels whose auction has not closed, and reads each parcel's page
once for its address (cached by auction number in .local/ca-tax-sales/).

    python -m pipeline.scrape_ca_tax_sales
    python -m pipeline.load_ca_tax_sales
"""
import argparse
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from pipeline.scraping.config import ScrapingSettings
from pipeline.scraping.http import PoliteClient

BASE = "https://www.bid4assets.com"
CALENDAR_URL = f"{BASE}/county-tax-sales"
AUCTIONS_API = f"{BASE}/api/storefront/auctions/index"
OUTPUT = Path("data/sheriff_sales/ca_bid4assets_tax_sales.json")
CACHE = Path(__file__).resolve().parents[2] / ".local" / "ca-tax-sales"
PARSER_VERSION = "ca_bid4assets_tax_sales_v1"
STOREFRONT_LINK = re.compile(r'href="(/storefront/[A-Za-z0-9]+)"')
TITLE = re.compile(r"<title>\s*(?:Bid4Assets:\s*)?(.*?)\s*</title>", re.S | re.I)
# "County of Santa Clara, CA Tax Defaulted ..." / "El Dorado County, CA Tax Defaulted ..."
CA_COUNTY = re.compile(r"^(?:County of\s+)?(.+?)(?:\s+County)?,\s*CA\b")
STOREFRONT_ID = re.compile(r"getauctiondisplay/(\d+)")
COLLECTION_ID = re.compile(r'"StorefrontCollectionId":(\d+)')
CITY_LINE = re.compile(r"^([A-Za-z][A-Za-z .'-]+),\s*CA\b\s*(\d{5})?")


def page_lines(page: str) -> list[str]:
    body = re.sub(r"(?s)<script.*?</script>|<style.*?</style>", "", page)
    return [line.strip() for line in html.unescape(re.sub(r"<[^>]+>", "\n", body)).splitlines() if line.strip()]


def storefront_paths(calendar_html: str) -> list[str]:
    return sorted(set(STOREFRONT_LINK.findall(calendar_html)))


def storefront_info(page: str) -> dict | None:
    """County, sale title, storefront id and closing-group ids of a California storefront."""
    title = TITLE.search(page)
    name = html.unescape(" ".join(title.group(1).split())) if title else ""
    county = CA_COUNTY.match(name)
    storefront = STOREFRONT_ID.search(page)
    if not county or not storefront or re.search(r"(?i)timeshare", name):
        return None
    return {"county": county.group(1).strip(), "title": name, "storefront_id": int(storefront.group(1)),
            "collections": sorted(set(int(found) for found in COLLECTION_ID.findall(page)))}


def location(page: str) -> tuple[str | None, str | None, str | None]:
    """Street, city and ZIP from an auction page's "Location:" lines."""
    lines = page_lines(page)
    for index, line in enumerate(lines[:-2]):
        if line == "Location:":
            street, city_line = lines[index + 1], lines[index + 2]
            match = CITY_LINE.match(city_line)
            if match and re.match(r"\d", street):
                return " ".join(street.split()), match.group(1).strip().title(), match.group(2)
            return None, None, None
    return None, None, None


def apn_of(title: str) -> str | None:
    """'County of Santa Clara, CA: 028-04-048' -> '028-04-048'."""
    match = re.search(r":\s*([\w-]+)\s*$", title or "")
    return match.group(1) if match else None


def parcels(client: PoliteClient, info: dict, now: datetime) -> list[dict]:
    rows = {}
    for collection in info["collections"]:
        response = client.post(AUCTIONS_API, params={"take": 9999, "skip": 0, "page": 1, "pageSize": 9999},
                               json={"storefrontId": info["storefront_id"], "storefrontCollectionId": collection})
        response.raise_for_status()
        for row in response.json().get("data") or []:
            rows[row["auctionID"]] = row
    found = []
    for auction_id, row in sorted(rows.items()):
        closes = row.get("bidCloseTime") or row.get("actualCloseTime")
        if not closes or datetime.fromisoformat(closes) < now.replace(tzinfo=None):
            continue
        cached = CACHE / "auctions" / f"{auction_id}.json"
        if cached.exists():
            street, city, zip_code = json.loads(cached.read_text())
        else:
            page = client.get(f"{BASE}/auction/index/{auction_id}")
            page.raise_for_status()
            street, city, zip_code = location(page.text)
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_text(json.dumps([street, city, zip_code]))
        found.append({
            "case": apn_of(row.get("asset_title")) or str(auction_id), "auction_id": auction_id,
            "apn": apn_of(row.get("asset_title")), "sale_date": closes[:10], "opens": row.get("bidOpenTime"),
            "closes": closes, "minimum_bid": row.get("minimumBid"), "street": street, "city": city,
            "zip_code": zip_code, "auction_url": f"{BASE}/auction/index/{auction_id}",
        })
    return found


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc)
    sales = []
    with PoliteClient(ScrapingSettings.from_env()) as client:
        calendar = client.get(CALENDAR_URL)
        calendar.raise_for_status()
        for path in storefront_paths(calendar.text):
            page = client.get(BASE + path)
            if not page.is_success:
                continue
            info = storefront_info(page.text)
            if not info:
                continue
            found = parcels(client, info, now)
            if found:
                print(f"{info['county']}: {info['title']}: {len(found)} open parcels "
                      f"({sum(bool(p['street']) for p in found)} with an address)", flush=True)
                sales.append({**info, "url": BASE + path, "parcels": found})
    snapshot = {"source_system": "ca_bid4assets_tax_sale", "state": "CA", "source_url": CALENDAR_URL,
                "scraped_at": now.isoformat(), "parser_version": PARSER_VERSION, "sales": sales}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, indent=1) + "\n")
    print(f"California: {len(sales)} sales, {sum(len(s['parcels']) for s in sales)} parcels -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
