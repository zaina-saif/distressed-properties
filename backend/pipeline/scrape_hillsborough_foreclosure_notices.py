"""Collect address-bearing Hillsborough foreclosure auction notices.

These are published notices, not the clerk's live RealAuction calendar. A sale
may be cancelled or rescheduled after publication; imported status is unverified.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

INDEX_URL = "https://legals.businessobserverfl.com/news/hillsborough/"
OUTPUT = Path("data/sheriff_sales/hillsborough_foreclosure_notices.json")
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
DATE_PATTERNS = (
    re.compile(rf"\b(?:on|at)\s+(?:the\s+)?(\d{{1,2}})(?:st|nd|rd|th)?\s+day\s+of\s+({MONTHS}),?\s+(20\d{{2}})\b", re.I),
    re.compile(rf"\b(?:on|at)\s+({MONTHS})\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(20\d{{2}})\b", re.I),
)
ADDRESS_PATTERN = re.compile(
    r"(?:Property Address|property located at|commonly known as|also known as|a/k/a)\s*[:;,]?\s*"
    r"(\d{1,6}\s+[^\n;]{5,100}?,?\s*[A-Za-z .'-]+,?\s*FL\s*\d{5}(?:-\d{4})?)",
    re.I,
)
CASE_PATTERN = re.compile(r"\bCASE\s*(?:NO\.?|NUMBER|#)\s*[:.]?[ \t]*([A-Z0-9-]+(?:[ \t]+[A-Z0-9-]+){0,2})", re.I)


def discover(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    return [urljoin(INDEX_URL, a["href"]) for card in soup.select(".wrap__masonary-card")
            if (a := card.select_one("h4.card-title a")) and a.get("href")
            and "foreclosure" in card.get_text(" ", strip=True).lower()]


def parse_notice(html: str, url: str, today: date | None = None) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")
    body = soup.select_one(".story_body")
    if not body:
        return None
    lines = [line.strip() for line in body.get_text("\n", strip=True).splitlines() if line.strip()]
    notice = "\n".join(lines)
    if not re.search(r"NOTICE\s+OF\s+(?:FORECLOSURE\s+)?SALE", notice, re.I):
        return None
    if not re.search(r"hillsborough\s*\.?\s*realforeclose\.com", notice, re.I):
        return None
    dates = [m for pattern in DATE_PATTERNS for m in pattern.finditer(notice)]
    if not dates:
        return None
    # The judgment/order date often precedes the actual sale date. Prefer the
    # date closest to the auction-site reference, rather than the first date.
    site = re.search(r"hillsborough\s*\.?\s*realforeclose\.com", notice, re.I)
    match = min(dates, key=lambda m: abs(m.start() - site.start()))
    groups = match.groups()
    day, month, year = (groups[0], groups[1], groups[2]) if groups[0].isdigit() else (groups[1], groups[0], groups[2])
    sale_date = datetime.strptime(f"{month} {day} {year}", "%B %d %Y").date()
    # The clerk's foreclosure auction starts at 10 a.m.; without a live status
    # feed, same-day notices are not safe to display as upcoming.
    if sale_date <= (today or date.today()):
        return None
    address_match = ADDRESS_PATTERN.search(notice)
    case_match = CASE_PATTERN.search(notice)
    if not address_match or not case_match:
        return None
    address = " ".join(address_match.group(1).split()).rstrip(".,")
    city_match = re.search(r",\s*([^,]+?),?\s*FL\s*(\d{5})", address, re.I)
    if not city_match:
        return None
    street = address[:city_match.start()].rstrip(" ,")
    case_tokens = case_match.group(1).strip().rstrip(".,").split()
    case_number = case_tokens[0] if "-" in case_tokens[0] else "-".join(case_tokens[:3])
    notice_id = (soup.select_one("h1") or soup.new_tag("h1")).get_text(" ", strip=True)
    published = soup.select_one('meta[property="article:published_time"]')
    return {"source_system": "fl_hillsborough_published_foreclosure_notice",
            "source_url": url, "notice_id": notice_id, "publication_date": published.get("content", "")[:10] if published else None,
            "sale_date": sale_date.isoformat(), "court_case_number": case_number,
            "address": f"{street}, {city_match.group(1).strip()}, FL {city_match.group(2)}",
            "street_address": street, "city": city_match.group(1).strip(),
            "zip_code": city_match.group(2), "county": "Hillsborough", "state": "FL",
            "notice_text": notice[:12000], "status": "scheduled_unverified"}


def collect(max_pages: int = 12, delay: float = 0.5, today: date | None = None) -> dict:
    records_by_case: dict[str, dict] = {}
    checked = (today or date.today()).isoformat()
    with httpx.Client(timeout=30, follow_redirects=True,
                      headers={"User-Agent": "nj-sheriff-sale-platform/1.0 (public notice research)"}) as client:
        for page in range(1, max_pages + 1):
            response = client.get(INDEX_URL, params={"page": page})
            response.raise_for_status()
            urls = discover(response.text)
            if not urls:
                break
            for url in urls:
                time.sleep(delay)
                detail = client.get(url)
                detail.raise_for_status()
                record = parse_notice(detail.text, url, today)
                if record:
                    key = record["court_case_number"].upper()
                    previous = records_by_case.get(key)
                    if previous is None or (record["publication_date"] or "") > (previous["publication_date"] or ""):
                        records_by_case[key] = record
            time.sleep(delay)
    return {"source_index_url": INDEX_URL, "source_checked_date": checked,
            "coverage_note": "Published notices with an explicit address, case number, and future auction date; not the live clerk calendar. Cancellation and rescheduling are unverified.",
            "pages_checked": max_pages, "records": sorted(records_by_case.values(), key=lambda r: (r["sale_date"], r["court_case_number"]))}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", type=int, default=12)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    snapshot = collect(args.pages, args.delay)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, indent=2) + "\n")
    print(json.dumps({"records": len(snapshot["records"]), "output": str(args.output)}))


if __name__ == "__main__":
    main()
