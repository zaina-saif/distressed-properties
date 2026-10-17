"""Harris County, TX trustee-sale notices from the County Clerk's foreclosure search.

Texas mortgage foreclosures are mostly non-judicial: a substitute trustee sells the
property on the first Tuesday of the month, and the Notice of Trustee's Sale must be
filed with the county clerk at least 21 days before (Tex. Prop. Code 51.002). The
Harris County Clerk lists those notices by sale month at FRCL_R.aspx (an ASP.NET
form, no CAPTCHA; robots.txt only disallows /Forms/) and serves each notice as a
scanned PDF. This collector lists every upcoming sale month, downloads each notice
once, reads it with macOS Vision OCR (pipeline/ocr_pdf_macos.swift, so it runs on
the operator's Mac) and parses it with parse_tx_trustee_notice.

PDFs and OCR text are cached by document number in .local/harris-trustee-notices/;
they contain the borrowers' names, so they stay there. The snapshot written to
data/sheriff_sales/ keeps only the parsed property, sale and lender fields.

    python -m pipeline.scrape_harris_trustee_notices                 # every upcoming sale month
    python -m pipeline.scrape_harris_trustee_notices --limit 40      # first 40 notices, for testing
    python -m pipeline.scrape_harris_trustee_notices --no-ocr        # list and download only
"""
import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from pipeline.collect_nyc_kings_foreclosure_pdfs import macos_ocr
from pipeline.parse_tx_trustee_notice import PARSER_VERSION, parse_notice
from pipeline.scraping.config import ScrapingSettings
from pipeline.scraping.http import PoliteClient

SEARCH_URL = "https://www.cclerk.hctx.net/applications/websearch/FRCL_R.aspx"
FIELD = "ctl00$ContentPlaceHolder1$"
DOC_ID = re.compile(r"FRCL-\d{4}-\d+")
CACHE = Path(__file__).resolve().parents[2] / ".local" / "harris-trustee-notices"
OUTPUT = Path("data/sheriff_sales/tx_harris_trustee_notices.json")


def hidden_fields(soup: BeautifulSoup) -> dict:
    return {tag["name"]: tag.get("value", "") for tag in soup.select("input[type=hidden]") if tag.get("name")}


def month_options(soup: BeautifulSoup) -> list[int]:
    return [int(option["value"]) for option in soup.select(f"select[name='{FIELD}ddlMonth'] option")
            if option.get("value", "").isdigit()]


def year_options(soup: BeautifulSoup) -> list[int]:
    return [int(option["value"]) for option in soup.select(f"select[name='{FIELD}ddlYear'] option")
            if option.get("value", "").isdigit()]


def result_rows(soup: BeautifulSoup) -> list[dict]:
    """Rows of the results grid: document number, sale date, file date, pages and the PDF link."""
    rows = []
    for row in soup.select("tr"):
        link = row.find("a", href=re.compile(r"ViewECdocs\.aspx"))
        cells = [cell.get_text(" ", strip=True) for cell in row.find_all("td")]
        doc = DOC_ID.search(" ".join(cells)) if link else None
        if not doc or len(cells) < 4:
            continue
        rows.append({"doc_id": doc.group(), "sale_date": _date(cells[2]), "file_date": _date(cells[3]),
                     "pages": int(cells[4]) if len(cells) > 4 and cells[4].isdigit() else None,
                     "href": link["href"]})
    return rows


def _date(value: str) -> str | None:
    try:
        return datetime.strptime(value.strip(), "%m/%d/%Y").date().isoformat()
    except ValueError:
        return None


class ClerkSearch:
    """The FRCL_R.aspx form: each step posts the page's view state back."""

    def __init__(self, client: PoliteClient):
        self.client = client
        self.soup = self._soup(client.get(SEARCH_URL))

    @staticmethod
    def _soup(response) -> BeautifulSoup:
        response.raise_for_status()
        return BeautifulSoup(response.text, "html.parser")

    def _post(self, **fields) -> BeautifulSoup:
        data = hidden_fields(self.soup) | {f"{FIELD}rbtlDate": "SaleDate", f"{FIELD}txtFileNo": ""} | fields
        self.soup = self._soup(self.client.post(SEARCH_URL, data=data))
        return self.soup

    def years(self) -> list[int]:
        return year_options(self.soup)

    def months(self, year: int) -> list[int]:
        self._post(**{f"{FIELD}ddlYear": str(year), f"{FIELD}ddlMonth": "Select -", "__EVENTTARGET": f"{FIELD}ddlYear"})
        return month_options(self.soup)

    def notices(self, year: int, month: int) -> list[dict]:
        """Every notice for sales in that month, page by page."""
        selection = {f"{FIELD}ddlYear": str(year), f"{FIELD}ddlMonth": str(month)}
        # Start over: the grid keeps its page across searches, and the form only
        # accepts a month of the year it shows.
        self.soup = self._soup(self.client.get(SEARCH_URL))
        self.months(year)
        soup = self._post(**selection, **{f"{FIELD}btnSearch": "Search"})
        rows, page = result_rows(soup), 1
        while f"Page${page + 1}" in str(soup):
            page += 1
            soup = self._post(**selection, __EVENTTARGET=f"{FIELD}GridView1", __EVENTARGUMENT=f"Page${page}")
            rows += result_rows(soup)
        return rows


def first_tuesday(year: int, month: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(1 - first.weekday()) % 7)


def upcoming_months(search: ClerkSearch, today: date) -> list[tuple[int, int]]:
    """Months the clerk lists notices for whose sale day (the first Tuesday) is today or later."""
    months = []
    for year in sorted(year for year in search.years() if year >= today.year):
        months += [(year, month) for month in search.months(year) if first_tuesday(year, month) >= today]
    return sorted(months)


def download(client: PoliteClient, row: dict) -> Path:
    path = CACHE / "pdfs" / f"{row['doc_id']}.pdf"
    if path.exists() and path.stat().st_size:
        return path
    response = client.get(str(httpx.URL(SEARCH_URL).join(row["href"])))
    response.raise_for_status()
    if not response.content.startswith(b"%PDF"):
        raise RuntimeError(f"{row['doc_id']}: the clerk returned {response.headers.get('content-type')}, not a PDF")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    return path


def ocr(pdf: Path) -> str:
    """OCR text, cached next to the PDFs by document number."""
    cached = CACHE / "text" / f"{pdf.stem}.txt"
    if cached.exists():
        return cached.read_text()
    text = macos_ocr(pdf)
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(text)
    return text


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, help="process only the first N notices (testing)")
    parser.add_argument("--no-ocr", action="store_true", help="list and download only")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    if not args.no_ocr and sys.platform != "darwin":
        parser.error("OCR uses macOS Vision: run this on the operator's Mac, or pass --no-ocr")

    today = date.today()
    with PoliteClient(ScrapingSettings.from_env()) as client:
        search = ClerkSearch(client)
        months = upcoming_months(search, today)
        rows = []
        for year, month in months:
            found = search.notices(year, month)
            print(f"{year}-{month:02d}: {len(found)} notices", flush=True)
            rows += found
        # A notice is filed once per sale date; keep the first row of any repeat.
        rows = list({row["doc_id"]: row for row in reversed(rows)}.values())[::-1]
        rows = [row for row in rows if row["sale_date"] and row["sale_date"] >= today.isoformat()]
        if args.limit:
            rows = rows[:args.limit]
        notices, failures = [], []
        for number, row in enumerate(rows, 1):
            try:
                pdf = download(client, row)
                text = None if args.no_ocr else ocr(pdf)
            except Exception as exc:  # one bad notice must not stop the month
                failures.append({"doc_id": row["doc_id"], "error": str(exc)[:300]})
                continue
            record = {key: row[key] for key in ("doc_id", "sale_date", "file_date", "pages")}
            if text is not None:
                record |= parse_notice(text)
            notices.append(record)
            if number % 25 == 0:
                print(f"  {number}/{len(rows)}", flush=True)

    snapshot = {
        "source_system": "tx_county_clerk_trustee_sale", "state": "TX", "county": "Harris",
        "source_url": SEARCH_URL, "scraped_at": datetime.now(timezone.utc).isoformat(),
        "parser_version": PARSER_VERSION, "sale_months": [f"{y}-{m:02d}" for y, m in months],
        "complete": not args.limit and not failures, "notices": notices, "failures": failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, indent=2))
    with_address = sum(1 for notice in notices if notice.get("street"))
    print(f"{len(notices)} notices ({with_address} with a street address), {len(failures)} failures -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
