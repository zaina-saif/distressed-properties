"""Delaware County, PA sheriff's sales from the Sheriff's monthly lists.

The Delaware County Sheriff's Real Estate Department posts two PDFs each month (sales on
the third Friday): "List of Properties for Current Month" and "List of Properties
Continued from Prior Months" (delcopa.gov/sheriffs-office/real-estate-department-sheriff-sales;
the /sheriff/pdf/listN.pdf links open a page that links the file). Both have a text layer
laid out in columns: item number, municipality and street, term & number (court case),
defendants' names, debt (and the 10% deposit) and the plaintiff's attorney. Rows are
rebuilt from word positions (pdfplumber); the names column is never read. A line such as
"CONTINUED TO DECEMBER 18 2026" (still scheduled, on that date) or "STAYED" after a row
is that row's status.

The snapshot has the shape scrape_pa_sale_listing writes and loads with load_pa_sales:

    python -m pipeline.scrape_pa_delaware_sheriff_sales
    python -m pipeline.load_pa_sales --counties Delaware
"""
import argparse
import io
import json
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urljoin

import pdfplumber

from pipeline.scraping.config import ScrapingSettings
from pipeline.scraping.http import PoliteClient

PAGE = "https://www.delcopa.gov/sheriffs-office/real-estate-department-sheriff-sales"
OUTPUT = Path("data/sheriff_sales/pa_delaware_sheriff_sales.json")
# Left edges of the columns (the page is 1008 points wide); "Name" (about 487) is skipped.
ITEM, LOCATION, CASE, NAME, DEBT, ATTORNEY = 30, 200, 395, 480, 700, 800
ITEM_START = re.compile(r"^(\d+\.|\d+-[A-Za-z]+\d{4})$")
CASE_NO = re.compile(r"^\d{2}-\d{6}$")
HEADING = re.compile(r"(?:Sale|List) for ([A-Z][a-z]+ \d{1,2}, \d{4})")
CONTINUED = re.compile(r"CONTINUED TO ([A-Z]+ \d{1,2},? \d{4})", re.I)
MONEY = re.compile(r"^\$[\d,]+\.\d{2}$")


def list_links(page: str, base: str) -> list[str]:
    return [urljoin(base, link) for link in dict.fromkeys(re.findall(r'href="([^"]*/sheriff/pdf/list\d\.pdf)"', page))]


def lines_of(pdf_bytes: bytes) -> list[tuple[int, float, list[tuple[float, str]]]]:
    """(page, top, [(x, text)]) per printed line."""
    lines = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for number, page in enumerate(pdf.pages, 1):
            grouped: dict[int, list[tuple[float, str]]] = {}
            for word in page.extract_words(keep_blank_chars=True, x_tolerance=2):
                grouped.setdefault(round(word["top"] / 3), []).append((word["x0"], word["text"].strip()))
            lines += [(number, key * 3, sorted(words)) for key, words in sorted(grouped.items())]
    return lines


def rows_from(lines, sale_day: date) -> list[dict]:
    starts = [(index, page, top) for index, (page, top, words) in enumerate(lines)
              if words and words[0][0] < LOCATION and ITEM_START.match(words[0][1])]
    rows = []
    for position, (index, page, top) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        # The debt column is centred on the row, so it can print a few points above the item number.
        block = [line for line in lines[max(0, index - 1):end] if line[0] == page and line[1] >= top - 6]
        location = [text for _, _, words in block for x, text in words if LOCATION <= x < CASE]
        case = next((text for _, _, words in block for x, text in words if CASE <= x < NAME and CASE_NO.match(text)), None)
        amounts = [text for _, _, words in block for x, text in words if DEBT <= x < ATTORNEY and MONEY.match(text)]
        attorney = " ".join(text for _, line_top, words in block if abs(line_top - top) < 2
                            for x, text in words if x >= ATTORNEY)
        notes = [text for _, line_top, words in block if line_top > top for x, text in words if x < LOCATION]
        if not case or len(location) < 2:
            continue
        status, when, raw = "scheduled", sale_day, "sheriff's sale"
        for note in notes:
            continued = CONTINUED.search(note)
            if continued:
                # Continued to this or a later sale: still an open sale, on that date.
                raw = note
                when = datetime.strptime(continued.group(1).replace(",", "").title(), "%B %d %Y").date()
            elif "STAY" in note.upper():
                status, raw = "stayed", note
        municipality = re.sub(r"\s+(Twp\.?|Township|Boro\.?|Borough)$", "", location[0]).strip()
        rows.append({"term_and_number": case, "municipality": location[0], "city": municipality,
                     "street": location[1].strip(" ,"), "sale_date": when, "status": status, "raw_status": raw,
                     "debt": float(amounts[0].strip("$").replace(",", "")) if amounts else None,
                     "attorney": attorney or None})
    return rows


def record(row: dict, url: str) -> dict:
    """A record in scrape_pa_sale_listing's shape (RawSheriffSale), without the defendants."""
    return {"county": "Delaware", "state": "PA", "sheriff_number": row["term_and_number"],
            "address": f"{row['street']}, {row['city']}", "sale_date": row["sale_date"].isoformat(),
            "status": row["status"], "upset_price": None, "source_url": url,
            "raw_payload": {"municipality": row["municipality"], "township": row["municipality"],
                            "attorney": row["attorney"], "raw_status": row["raw_status"], "debt": row["debt"]},
            "plaintiff": None, "defendant": None,
            "judgment_amount": row["debt"], "court_case_number": row["term_and_number"]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    records: dict[str, dict] = {}
    with PoliteClient(ScrapingSettings.from_env()) as client:
        page = client.get(PAGE)
        page.raise_for_status()
        for link in list_links(page.text, str(page.url)):
            holder = client.get(link)  # a page that links the month's file
            holder.raise_for_status()
            files = re.findall(r'href="(/sites/default/files/[^"]*list\d[^"]*\.pdf)"', holder.text, re.I)
            if not files:
                raise SystemExit(f"No list file linked from {link}; previous snapshot kept")
            url = urljoin(str(holder.url), files[0])
            pdf = client.get(url)
            pdf.raise_for_status()
            lines = lines_of(pdf.content)
            heading = next((HEADING.search(text) for _, _, words in lines[:5] for _, text in words
                            if HEADING.search(text)), None)
            if not heading:
                raise SystemExit(f"No sale date heading in {url}; previous snapshot kept")
            sale_day = datetime.strptime(heading.group(1), "%B %d, %Y").date()
            for row in rows_from(lines, sale_day):
                if row["sale_date"] >= date.today():
                    records[row["term_and_number"]] = record(row, url)
    if not records:
        raise SystemExit("Delaware County: no upcoming sales read; previous snapshot kept")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(sorted(records.values(), key=lambda r: r["sheriff_number"]), indent=2) + "\n")
    print(f"Delaware: {len(records)} upcoming sales -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
