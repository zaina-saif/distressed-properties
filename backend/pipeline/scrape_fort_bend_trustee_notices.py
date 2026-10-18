"""Fort Bend County, TX trustee-sale notices from the County Clerk's monthly foreclosure list.

The Fort Bend County Clerk posts every Notice of Trustee's Sale for the coming sale as one
scanned PDF per month ("November-2026.pdf", posted by the 20th of the month before) on its
Search for Foreclosures page. Each notice's first page carries the clerk's file stamp
("2026 AUG 20 AM 10:34"), which marks where one notice ends and the next begins and gives
its filing date. The collector downloads each upcoming month's PDF, OCRs it page by page
with macOS Vision (cached in .local/fort-bend-trustee-notices/, which also holds the
borrowers' names, so it stays there), splits it where a notice's title or stamp starts a page and parses each notice with
parse_tx_trustee_notice. The clerk prints no document numbers on the list, so a notice is
keyed by address, ZIP and sale date; notices without a street address are not loaded.

    python -m pipeline.scrape_fort_bend_trustee_notices              # macOS Vision OCR
    python -m pipeline.scrape_fort_bend_trustee_notices --text-layer # the PDF's own (rougher) text, any OS
    python -m pipeline.load_tx_trustee_sales --input data/sheriff_sales/tx_fort_bend_trustee_notices.json
"""
import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader, PdfWriter

from pipeline.collect_nyc_kings_foreclosure_pdfs import macos_ocr
from pipeline.parse_tx_trustee_notice import PARSER_VERSION, parse_notice
from pipeline.scrape_harris_trustee_notices import first_tuesday
from pipeline.scraping.config import ScrapingSettings
from pipeline.scraping.http import PoliteClient

PAGE_URL = "https://www.fortbendcountytx.gov/government/departments/county-clerk/search-for-foreclosures"
MONTH_PDF = re.compile(r"/research-foreclosures/([A-Za-z]+)-(\d{4})\.pdf$")
MONTHS = {name: number for number, name in enumerate(
    "january february march april may june july august september october november december".split(), 1)}
CACHE = Path(__file__).resolve().parents[2] / ".local" / "fort-bend-trustee-notices"
OUTPUT = Path("data/sheriff_sales/tx_fort_bend_trustee_notices.json")
# The clerk's file stamp on a notice's first page, in either of its forms:
# "2026 AUG 20 AM 10:34" or "FILED FOR RECORD ... AUG 18 2026" (OCR splits days: "SEP 1 7 2026").
STAMP_YEAR_FIRST = re.compile(r"(?m)^\W{0,3}(20\d{2})\s+(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\.?\s+(\d{1,2})\b")
STAMP_YEAR_LAST = re.compile(r"(?m)^\W{0,3}(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\.?\s+(\d)\s?(\d)?\s*,?\s+(20\d{2})\b")
STAMP_MONTHS = {name: number for number, name in enumerate(
    "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split(), 1)}
# A notice's own title near the top of its first page (not "... in this Notice of Sale").
HEADING = re.compile(r"(?im)^\W{0,3}(?:appointment\s+of\s+substitute\s+trustees?\s+and\s+)?notice\s+of\s+"
                     r"(?:(?:substitute\s+)?trustee.{0,3}s?\s+(?:foreclosure\s+)?sale|foreclosure\s+sale|sale)\b")
# Leading pages of the list (the venue order and the clerk's courtesy notice), not notices.
NOT_A_NOTICE = re.compile(r"(?i)foreclosure\s+sales\s+notice|as\s+a\s+courtesy|courtesy\s+notice")


def filing_date(text: str) -> str | None:
    found = STAMP_YEAR_FIRST.search(text)
    if found:
        year, month, day = found.group(1), found.group(2), found.group(3)
    else:
        found = STAMP_YEAR_LAST.search(text)
        if not found:
            return None
        month, day, year = found.group(1), found.group(2) + (found.group(3) or ""), found.group(4)
    try:
        return date(int(year), STAMP_MONTHS[month], int(day)).isoformat()
    except ValueError:
        return None


def starts_notice(text: str) -> bool:
    top = "\n".join(text.splitlines()[:18])
    return not NOT_A_NOTICE.search(text[:600]) and bool(HEADING.search(top) or filing_date(text))


def month_pdfs(html: str, today: date) -> list[tuple[date, str]]:
    """(sale date, PDF URL) for each list on the page whose sale day is today or later."""
    found = {}
    for link in BeautifulSoup(html, "html.parser").find_all("a", href=True):
        match = MONTH_PDF.search(link["href"])
        if match and match.group(1).lower() in MONTHS:
            sale_date = first_tuesday(int(match.group(2)), MONTHS[match.group(1).lower()])
            if sale_date >= today:
                found[sale_date] = str(httpx.URL(PAGE_URL).join(link["href"]))
    return sorted(found.items())


def download(client: PoliteClient, url: str, folder: Path) -> Path:
    """The month's PDF, fetched again (and its OCR cleared) when the clerk replaces it."""
    path = folder / url.rsplit("/", 1)[-1]
    size = client.head(url).headers.get("content-length")
    if path.exists() and size and int(size) == path.stat().st_size:
        return path
    response = client.get(url)
    response.raise_for_status()
    if not response.content.startswith(b"%PDF"):
        raise RuntimeError(f"{url}: not a PDF")
    folder.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    for cached in (folder / "text").glob("*.txt"):
        cached.unlink()
    return path


def page_texts(pdf: Path, text_layer: bool) -> list[str]:
    """Each page's text: macOS Vision OCR, one page at a time and cached, or the PDF's own text layer."""
    reader = PdfReader(pdf)
    if text_layer:
        return [page.extract_text() or "" for page in reader.pages]
    text_dir, single = pdf.parent / "text", pdf.parent / "page.pdf"
    text_dir.mkdir(exist_ok=True)
    texts = []
    for number, page in enumerate(reader.pages):
        cached = text_dir / f"{number:04d}.txt"
        if not cached.exists():
            writer = PdfWriter()
            writer.add_page(page)
            with single.open("wb") as handle:
                writer.write(handle)
            cached.write_text(macos_ocr(single))
        texts.append(cached.read_text())
        if number and number % 50 == 0:
            print(f"  {pdf.name}: {number}/{len(reader.pages)} pages read", flush=True)
    single.unlink(missing_ok=True)
    return texts


def split_notices(pages: list[str]) -> list[tuple[int, str, str | None]]:
    """(first page, text, filing date) for each notice: a page with the notice's title near
    its top or the clerk's file stamp starts one, and the pages after it belong to it."""
    notices = []
    for number, text in enumerate(pages):
        if starts_notice(text):
            notices.append([number, text])
        elif notices:
            notices[-1][1] += "\n" + text
    return [(first, text, filing_date(text)) for first, text in notices]


def notice_records(pages: list[str], sale_date: date) -> list[dict]:
    records = {}
    for first_page, text, filed in split_notices(pages):
        parsed = parse_notice(text)
        street, zip_code = parsed.get("street"), parsed.get("zip_code")
        key = f"{street.upper()}|{zip_code}|{sale_date.isoformat()}" if street else f"page-{first_page + 1}"
        records.setdefault(key, {"doc_id": key, "clerk_number": False, "sale_date": sale_date.isoformat(),
                                 "file_date": filed, "list_page": first_page + 1} | parsed)
    return list(records.values())


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--text-layer", action="store_true", help="read the PDF's own text instead of OCR")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    if not args.text_layer and sys.platform != "darwin":
        parser.error("OCR uses macOS Vision: run this on the operator's Mac, or pass --text-layer")
    today = date.today()
    notices, months = [], []
    with PoliteClient(ScrapingSettings.from_env()) as client:
        response = client.get(PAGE_URL)
        response.raise_for_status()
        for sale_date, url in month_pdfs(response.text, today):
            pdf = download(client, url, CACHE / sale_date.strftime("%Y-%m"))
            found = notice_records(page_texts(pdf, args.text_layer), sale_date)
            print(f"{sale_date}: {len(found)} notices ({sum(bool(n.get('street')) for n in found)} with a street address)")
            notices += found
            months.append(sale_date.strftime("%Y-%m"))
    if not notices:
        raise SystemExit("Fort Bend: no upcoming foreclosure list; previous snapshot kept")
    snapshot = {
        "source_system": "tx_county_clerk_trustee_sale", "state": "TX", "county": "Fort Bend", "source_url": PAGE_URL,
        "scraped_at": datetime.now(timezone.utc).isoformat(), "parser_version": PARSER_VERSION,
        "text_source": "pdf_text_layer" if args.text_layer else "macos_vision_ocr", "sale_months": months,
        "complete": True, "notices": notices, "failures": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, indent=1) + "\n")
    print(f"Fort Bend: {len(notices)} notices -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
