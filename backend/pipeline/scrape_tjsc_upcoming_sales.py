"""Scrape upcoming Illinois judicial sales from The Judicial Sales Corporation.

TJSC renders the sales grid client-side.  This scraper uses the public Chrome
channel so it works in environments where Playwright's bundled browser is not
installed, waits for the grid to populate, and advances the site's Next link
until it stops changing the grid.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

SOURCE_URL = "https://www.tjsc.com/sales/upcomingsales"
SOURCE_SYSTEM = "il_tjsc_upcoming_sales"
OUTPUT = Path("data/sheriff_sales/il_tjsc_upcoming_sales.json")
EXPECTED_HEADERS = [
    "sale date", "sale time", "file number", "case number", "firm name",
    "address", "city", "county", "zip code", "opening bid",
]


def _clean(value: str | None) -> str | None:
    value = re.sub(r"\s+", " ", (value or "")).strip()
    return value or None


def _money(value: str | None) -> float | None:
    if not value or value.strip().upper() in {"TBD", "N/A", "NA", "-"}:
        return None
    match = re.search(r"-?[\d,]+(?:\.\d{1,2})?", value)
    return float(match.group(0).replace(",", "")) if match else None


def _sale_datetime(sale_date: str | None, sale_time: str | None) -> str | None:
    if not sale_date:
        return None
    for fmt in ("%m/%d/%Y %I:%M %p", "%m/%d/%Y"):
        try:
            text = f"{sale_date} {sale_time}" if sale_time and fmt != "%m/%d/%Y" else sale_date
            return datetime.strptime(text, fmt).isoformat()
        except ValueError:
            continue
    return None


def _table(page: Page):
    tables = page.locator("table")
    for index in range(tables.count()):
        table = tables.nth(index)
        if table.locator("tr").count() < 2:
            continue
        headers = [_clean(v).lower() for v in table.locator("tr").first.locator("th,td").all_inner_texts()]
        if "case number" in headers and "opening bid" in headers:
            return table, headers
    raise RuntimeError("TJSC sales table was not found after waiting for the dynamic page")


def extract_page_records(page: Page) -> list[dict]:
    table, headers = _table(page)
    index = {header: i for i, header in enumerate(headers) if header}
    records: list[dict] = []
    for row in table.locator("tr").all()[1:]:
        cells = [_clean(cell) for cell in row.locator("th,td").all_inner_texts()]
        if len(cells) < len(headers) or not cells[index["case number"]]:
            continue
        # The site renders a second header row inside the table body.
        if cells[index["case number"]].lower() == "case number":
            continue
        record = {
            "source_system": SOURCE_SYSTEM,
            "state": "IL",
            "status": "scheduled",
            "source_url": SOURCE_URL,
            "court_case_number": cells[index["case number"]],
            "file_number": cells[index["file number"]],
            "street_address": cells[index["address"]],
            "city": cells[index["city"]],
            "county": cells[index["county"]] or "Unknown",
            "zip_code": cells[index["zip code"]],
            "opening_bid": _money(cells[index["opening bid"]]),
            "sale_date": _sale_datetime(cells[index["sale date"]], cells[index["sale time"]]),
            "raw_row": dict(zip(headers, cells)),
        }
        records.append(record)
    return records


def _page_signature(records: list[dict]) -> tuple:
    return tuple((r["court_case_number"], r["street_address"]) for r in records)


def scrape(*, max_pages: int = 500, visible: bool = False) -> dict:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=not visible)
        page = browser.new_page()
        page.goto(SOURCE_URL, wait_until="domcontentloaded", timeout=90_000)
        page.wait_for_timeout(8_000)
        try:
            page.wait_for_selector("table tr", timeout=30_000)
        except PlaywrightTimeoutError as exc:
            browser.close()
            raise RuntimeError("TJSC did not render its sales grid") from exc

        records: list[dict] = []
        seen: set[tuple[str, str]] = set()
        page_signatures: set[tuple] = set()
        for page_number in range(1, max_pages + 1):
            current = extract_page_records(page)
            signature = _page_signature(current)
            if signature in page_signatures:
                break
            page_signatures.add(signature)
            for record in current:
                key = (record["court_case_number"], record["street_address"])
                if key not in seen:
                    records.append(record)
                    seen.add(key)

            next_link = page.locator("a").filter(has_text=re.compile(r"^Next"))
            if not next_link.count():
                break
            class_name = (next_link.first.get_attribute("class") or "").lower()
            aria_disabled = (next_link.first.get_attribute("aria-disabled") or "").lower()
            if "disabled" in class_name or aria_disabled == "true":
                break
            try:
                next_link.first.click(timeout=10_000)
                # TJSC updates the table through a client-side callback.  A
                # short polling loop is more reliable than network-idle here,
                # because the page keeps analytics requests open.
                changed = False
                for _ in range(30):
                    page.wait_for_timeout(500)
                    if _page_signature(extract_page_records(page)) != signature:
                        changed = True
                        break
                if not changed:
                    break
            except PlaywrightTimeoutError:
                # A final Next click often leaves the last grid in place.
                if _page_signature(extract_page_records(page)) == signature:
                    break
        browser.close()

    return {
        "source_index_url": SOURCE_URL,
        "source_checked_date": date.today().isoformat(),
        "source_system": SOURCE_SYSTEM,
        "state": "IL",
        "records": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--max-pages", type=int, default=500)
    parser.add_argument("--visible", action="store_true")
    args = parser.parse_args()
    snapshot = scrape(max_pages=args.max_pages, visible=args.visible)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "records": len(snapshot["records"])}))


if __name__ == "__main__":
    main()
