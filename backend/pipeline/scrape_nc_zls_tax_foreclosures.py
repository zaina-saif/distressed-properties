"""North Carolina tax foreclosure sales from Zacchaeus Legal Services (zls-nc.com/listings).

North Carolina counties collect unpaid property taxes by foreclosure: the county's
attorney sues, and the property is sold at the courthouse, then stays open for ten days
of upset bids before the Clerk of Superior Court confirms the sale. Zacchaeus Legal
Services handles these for many county tax offices (Guilford's tax office points buyers
there) and lists every parcel on one page: tax office, parcel number, status, sale date,
upset-bid deadline, opening bid, current bid and address. No party names are shown.

The page shows its disclaimer first; agreeing sets the site's own "UserPropertyAgreement"
cookie, which the collector sets the same way. The list is a Blazor Server grid of 10 rows
per page, so it is read with a headless browser (BrowserManager: pacing, and a stop at any
verification challenge) by clicking "Next page" until the grid's row count is reached.
robots.txt allows everything but /auth/.

    python -m pipeline.scrape_nc_zls_tax_foreclosures
    python -m pipeline.load_nc_zls_tax_foreclosures

Locally, SCRAPER_BROWSER_CHANNEL=chrome uses the installed Chrome.
"""
import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeout

from pipeline.scraping.browser import BrowserManager

URL = "https://zls-nc.com/listings"
OUTPUT = Path("data/sheriff_sales/nc_zls_tax_foreclosures.json")
PARSER_VERSION = "nc_zls_listings_v1"
COLUMNS = ["tax_office", "parcel", "status", "sale_date", "upset_deadline", "opening_bid", "current_bid", "notice",
           "address"]
TOTAL = re.compile(r"Data grid with (\d+) rows")
MAX_PAGES = 200
# Town and city tax offices ZLS also lists, and their counties.
OFFICE_COUNTIES = {"City of Laurinburg": "Scotland", "Town of Williamston": "Martin", "Town of Maxton": "Robeson",
                   "City of Lumberton": "Robeson", "Town of Farmville": "Pitt", "Town of Plymouth": "Washington",
                   "Town of Columbia": "Tyrrell"}
# "210 Woodlawn St, West End, NC 27376" (the site marks every address with a warning sign)
ADDRESS = re.compile(r"^(?P<street>.+?),\s*(?P<city>[^,]+?),\s*NC\s*(?P<zip>\d{5})?\s*$")


def read_page(page, attempts: int = 20) -> list[list[str]]:
    """The grid rows on the current page; waits out the moment the app redraws the grid."""
    for _ in range(attempts):
        rows = page.locator("tr[data-visible-index]").evaluate_all(
            "rows => rows.map(row => Array.from(row.querySelectorAll('td')).map(td => td.innerText.trim()))")
        rows = [row[:len(COLUMNS)] for row in rows if len(row) >= len(COLUMNS) and row[1]]
        if rows:
            return rows
        page.wait_for_timeout(500)
    return []


def next_page(page, first: str) -> None:
    """Click "Next page" and wait for a new first row; a click sent before the app's live
    connection is up is dropped, so an unanswered click is repeated."""
    for _ in range(3):
        page.locator("button[aria-label='Next page']").first.click()
        try:
            page.wait_for_function(
                """first => { const cell = document.querySelector('tr[data-visible-index] td:nth-child(2)');
                              return cell && cell.innerText.trim() && cell.innerText.trim() !== first; }""",
                arg=first, timeout=10_000)
            return
        except PlaywrightTimeout:
            continue
    raise RuntimeError("ZLS listings: the next page did not load")


def collect(browser: BrowserManager) -> list[list[str]]:
    browser.page.context.add_cookies([{"name": "UserPropertyAgreement", "value": "true", "domain": "zls-nc.com",
                                       "path": "/", "secure": True}])
    browser.goto(URL, wait_until="domcontentloaded")
    page = browser.page
    page.wait_for_selector("text=/Data grid with \\d+ rows/", timeout=60_000)
    page.wait_for_timeout(2_000)
    total = int(TOTAL.search(page.locator("body").inner_text()).group(1))
    rows: dict[tuple[str, str], list[str]] = {}
    for _ in range(MAX_PAGES):
        current = read_page(page)
        if not current:
            raise RuntimeError(f"ZLS listings: an empty page after {len(rows)} of {total} rows")
        for row in current:
            rows[(row[0], row[1])] = row
        if len(rows) >= total:
            break
        next_page(page, current[0][1])
        browser.ensure_access()
    # A partial read must not replace the last complete snapshot.
    if len(rows) != total:
        raise RuntimeError(f"ZLS listings: read {len(rows)} rows, the site lists {total}")
    return list(rows.values())


def _date(value: str) -> str | None:
    match = re.match(r"(\d{1,2}/\d{1,2}/\d{4})", value or "")
    return datetime.strptime(match.group(1), "%m/%d/%Y").date().isoformat() if match else None


def parcel_from(row: list[str]) -> dict:
    values = dict(zip(COLUMNS, row))
    county = re.match(r"^(.+?) County\b", values["tax_office"])
    address = ADDRESS.match(values["address"].replace("⚠️", "").strip())
    return {
        "tax_office": values["tax_office"],
        "county": county.group(1).strip() if county else OFFICE_COUNTIES.get(values["tax_office"]),
        "parcel": values["parcel"], "status": values["status"], "sale_date": _date(values["sale_date"]),
        "upset_deadline": values["upset_deadline"] if _date(values["upset_deadline"]) else None,
        "opening_bid": values["opening_bid"] if values["opening_bid"].startswith("$") else None,
        "current_bid": values["current_bid"] if values["current_bid"].startswith("$") else None,
        "street": address.group("street").strip() if address else None,
        "city": address.group("city").strip() if address else None,
        "zip_code": address.group("zip") if address else None,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    with BrowserManager("nc-zls-tax-foreclosures") as browser:
        rows = collect(browser)
    parcels = sorted((parcel_from(row) for row in rows), key=lambda item: (item["tax_office"], item["parcel"]))
    snapshot = {"source_system": "nc_zls_tax_foreclosure", "state": "NC", "source_url": URL,
                "scraped_at": datetime.now(timezone.utc).isoformat(), "parser_version": PARSER_VERSION,
                "parcels": parcels}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, indent=1) + "\n")
    statuses: dict[str, int] = {}
    for parcel in parcels:
        statuses[parcel["status"]] = statuses.get(parcel["status"], 0) + 1
    print(f"ZLS: {len(parcels)} parcels {statuses} -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
