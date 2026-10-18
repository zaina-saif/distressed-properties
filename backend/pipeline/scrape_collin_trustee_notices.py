"""Collin County, TX trustee-sale notices from the County Clerk's foreclosure notices site.

The Collin County Clerk lists every Notice of Trustee's Sale posted for the coming sale
days at apps2.collincountytx.gov/ForeclosureNotices: street address with mailing city
and ZIP, city (or unincorporated area), sale date, filing date and appraisal property
type, with no party names. The site is a Blazor Server app that renders 25 notices per
page and pages over its live connection, so the collector reads it with a headless
browser (BrowserManager: pacing, and a stop at any verification challenge) and clicks
through the pages. It publishes no document numbers; a notice is keyed by address, ZIP
and sale date.

    python -m pipeline.scrape_collin_trustee_notices
    python -m pipeline.load_tx_trustee_sales --input data/sheriff_sales/tx_collin_trustee_notices.json

Locally, SCRAPER_BROWSER_CHANNEL=chrome uses the installed Chrome.
"""
import argparse
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeout

from pipeline.scraping.browser import BrowserManager

URL = "https://apps2.collincountytx.gov/ForeclosureNotices"
OUTPUT = Path("data/sheriff_sales/tx_collin_trustee_notices.json")
PARSER_VERSION = "tx_collin_foreclosure_notices_v1"
HEADER = re.compile(r"^(?P<street>.+?)\s*[\r\n]+\s*(?P<city>[A-Za-z .'-]+),\s*TX\s+(?P<zip>\d{5})", re.S)
FIELD = re.compile(r"(City|Sale Date|File Date|Property Type):\s*(.*)")
MAX_PAGES = 100
TOTAL = re.compile(r"\[\s*(\d+)\s*/\s*\d+\s*\]")
# Batches the clerk posts under a title instead of an address
# ("FILED 9/24/2026 - NOVEMBER SALE - MCKINNEY (2)"): there is nothing to place on a map.
BATCH = re.compile(r"(?i)^FILL?ED\b.*\bSALE\b")


def _date(value: str | None) -> str | None:
    try:
        return datetime.strptime((value or "").strip(), "%m/%d/%Y").date().isoformat()
    except ValueError:
        return None


def parse_row(header: str, fields: list[str]) -> dict | None:
    """One notice from its header ("1000 CANAL ST\\r\\nMCKINNEY, TX 75069") and its
    labeled fields; None when the address or sale date does not read."""
    match = HEADER.match(header.strip())
    values = dict(found.groups() for text in fields if (found := FIELD.search(text)))
    sale_date = _date(values.get("Sale Date"))
    if not match or not sale_date:
        return None
    street = " ".join(match["street"].split()).title()
    zip_code = match["zip"]
    return {
        "doc_id": f"{street.upper()}|{zip_code}|{sale_date}", "clerk_number": False,
        "sale_date": sale_date, "file_date": _date(values.get("File Date")),
        "street": street, "city": " ".join(match["city"].split()).title(), "zip_code": zip_code,
        "jurisdiction": (values.get("City") or "").strip() or None,
        "property_type": (values.get("Property Type") or "").strip() or None,
        "address_source": "clerk_list", "notice_kind": "deed_of_trust",
    }


def read_page(page, attempts: int = 20) -> list[tuple[str, list[str]]]:
    """The rows on the current page; waits out the moment the app redraws the list."""
    for _ in range(attempts):
        rows = page.locator("tr.mud-table-row").evaluate_all("""rows => rows.map(row => [
            (row.querySelector('p.list-header') || {}).textContent || '',
            Array.from(row.querySelectorAll('.mud-grid-item p')).map(p => p.innerText)])""")
        rows = [row for row in rows if row[0].strip()]
        if rows:
            return rows
        page.wait_for_timeout(500)
    return []


def total_notices(page) -> int:
    """The count the filters show ("All Dates [211 / 211]")."""
    match = TOTAL.search(page.locator("body").inner_text())
    if not match:
        raise RuntimeError("Collin notices: the page does not show how many notices it lists")
    return int(match.group(1))


def next_page(page, first: str) -> None:
    """Click "Next page" and wait for a new first row. A click sent before the app's live
    connection is up is dropped, so an unanswered click is repeated."""
    for _ in range(3):
        page.locator("button[aria-label='Next page']").click()
        try:
            page.wait_for_function(
                """first => { const header = document.querySelector('p.list-header');
                              return header && header.textContent.trim() && header.textContent !== first; }""",
                arg=first, timeout=10_000)
            return
        except PlaywrightTimeout:
            continue
    raise RuntimeError("Collin notices: the next page did not load")


def collect(browser: BrowserManager) -> list[tuple[str, list[str]]]:
    # The app keeps its connection open, so the network never stays idle for long; it
    # also redraws the server-rendered list once that connection starts.
    browser.goto(URL, wait_until="domcontentloaded")
    page = browser.page
    page.wait_for_selector("p.list-header", timeout=60_000)
    try:
        page.wait_for_load_state("networkidle", timeout=15_000)
    except PlaywrightTimeout:
        pass
    page.wait_for_timeout(2_000)
    total, rows = total_notices(page), []
    for _ in range(MAX_PAGES):
        current = read_page(page)
        if not current:
            raise RuntimeError(f"Collin notices: an empty page after {len(rows)} of {total} rows")
        rows += current
        if len(rows) >= total:
            break
        next_page(page, current[0][0])
        browser.ensure_access()
    # A partial read must not replace the last complete snapshot.
    if len(rows) != total:
        raise RuntimeError(f"Collin notices: read {len(rows)} rows, the site lists {total}")
    return rows


def notices_from(rows: list[tuple[str, list[str]]], today: date) -> tuple[list[dict], list[str], int]:
    """Upcoming notices, rows that did not read, and the number of untitled batches."""
    notices, unread, batches = {}, [], 0
    for header, fields in rows:
        if BATCH.match(header.strip()):
            batches += 1
            continue
        notice = parse_row(header, fields)
        if notice is None:
            unread.append(header.strip()[:80])
        elif notice["sale_date"] >= today.isoformat():
            notices[notice["doc_id"]] = notice
    return sorted(notices.values(), key=lambda notice: (notice["sale_date"], notice["doc_id"])), unread, batches


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    with BrowserManager("collin-foreclosure-notices") as browser:
        rows = collect(browser)
    notices, unread, batches = notices_from(rows, date.today())
    for header in unread:
        print(f"Collin: could not read {header!r}")
    if not notices:
        raise SystemExit("Collin foreclosure notices: none upcoming; previous snapshot kept")
    snapshot = {
        "source_system": "tx_county_clerk_trustee_sale", "state": "TX", "county": "Collin", "source_url": URL,
        "scraped_at": datetime.now(timezone.utc).isoformat(), "parser_version": PARSER_VERSION,
        "sale_months": sorted({notice["sale_date"][:7] for notice in notices}), "complete": not unread,
        "notices": notices, "batches_without_address": batches,
        "failures": [{"row": header} for header in unread],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, indent=1) + "\n")
    print(f"Collin: {len(rows)} rows, {len(notices)} upcoming notices, {batches} batches without an address"
          f" -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
