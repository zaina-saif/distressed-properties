"""Allegheny County, PA sheriff's sales from the Sheriff's posted sale lists.

The Allegheny County Sheriff (sheriffalleghenycounty.com, robots.txt allows everything;
the county's alleghenycounty.us pages refuse scripts and are not used) links each month's
"Sale List" PDF from its Sheriff's Sales page. The PDF has a text layer: a "Date of Sale:"
heading, then one block per property with sale number, case number, sale type (mortgage
foreclosure, tax or municipal lien), status ("Active", "Postponed to 5/3/2027", ...),
tracts and the "Cost & Tax Bid" (the opening bid), then plaintiff, attorney, defendants,
property address, municipality and parcel ID. Blocks are rebuilt from word positions
(pdfplumber); the defendants' column is never read, and neither are the comments.

The snapshot has the shape scrape_pa_sale_listing writes and loads with load_pa_sales:

    python -m pipeline.scrape_pa_allegheny_sheriff_sales
    python -m pipeline.load_pa_sales --counties Allegheny
"""
import argparse
import io
import json
import re
from datetime import date, datetime
from pathlib import Path

import pdfplumber

from pipeline.scraping.config import ScrapingSettings
from pipeline.scraping.http import PoliteClient

PAGE = "https://sheriffalleghenycounty.com/sheriffs-sales/"
OUTPUT = Path("data/sheriff_sales/pa_allegheny_sheriff_sales.json")
LIST_LINK = re.compile(r'href="(https://sheriffalleghenycounty\.com/wp-content/uploads/\d{4}/\d{2}/[^"]*Sale-List[^"]*\.pdf)"', re.I)
CASE = re.compile(r"^[A-Z]{2}-\d{2}-\d{3,7}$")
SALE_DAY = re.compile(r"[A-Z][a-z]+day, ([A-Z][a-z]+ \d{1,2}, \d{4})")
POSTPONED = re.compile(r"Postponed to (\d{1,2}/\d{1,2}/\d{4})", re.I)
MONEY = re.compile(r"\$([\d,]+\.\d{2})")
CITY_LINE = re.compile(r"^(.+?),\s*PA\s+(\d{5})")
# Pittsburgh streets carry the ward: "5415 Butler Street - 10TH", "227 MARLAND ST 30TH WARD", "229 Thornberry Drive -".
WARD = re.compile(r"\s*(?:-\s*(?:\d+(?:ST|ND|RD|TH))?|\d+(?:ST|ND|RD|TH)\s+WARD)\s*$", re.I)
# Left edges of the columns on the 792-point-wide pages.
SALE_TYPE, STATUS, TRACTS, BID, SERVICE = 160, 350, 480, 560, 660
ATTORNEY, DEFENDANT, PROPERTY, MUNICIPALITY, PARCEL = 160, 300, 450, 580, 665


def words_by_line(page) -> list[tuple[float, list[tuple[float, str]]]]:
    grouped: dict[int, list[tuple[float, str]]] = {}
    for word in page.extract_words(keep_blank_chars=True, x_tolerance=2):
        grouped.setdefault(round(word["top"] / 3), []).append((word["x0"], word["text"].strip()))
    return [(key * 3, sorted(words)) for key, words in sorted(grouped.items())]


def column(line_words, low, high) -> str:
    return " ".join(text for x, text in line_words if low <= x < high and text).strip()


def status_of(status: str, sale_day: date) -> tuple[str, date]:
    postponed = POSTPONED.search(status)
    if postponed:
        return "scheduled", datetime.strptime(postponed.group(1), "%m/%d/%Y").date()
    lowered = status.lower()
    if "stay" in lowered:
        return "stayed", sale_day
    if any(word in lowered for word in ("cancel", "withdraw", "settled", "satisf", "paid")):
        return "cancelled", sale_day
    return "scheduled", sale_day


def blocks(lines, sale_day: date) -> list[dict]:
    """One dict per property: the case line and the property details below it."""
    starts = [index for index, (_, words) in enumerate(lines)
              if any(CASE.match(text) and 70 <= x < SALE_TYPE for x, text in words)]
    found = []
    for position, index in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        top = lines[index][0]
        # Status and bid can print a few points above or below the case number.
        header = [word for line_top, words in lines[max(0, index - 1):end] if abs(line_top - top) <= 6 for word in words]
        case = next(text for x, text in header if CASE.match(text) and 70 <= x < SALE_TYPE)
        status_text = column(header, STATUS, TRACTS)
        bid = MONEY.search(column(header, BID, SERVICE))
        label = next((i for i in range(index, end) if any(t.startswith("Property") for _, t in lines[i][1])), None)
        if label is None:
            continue
        details = []
        for line_top, words in lines[label + 1:end]:
            if any(t.startswith("Comments") for _, t in words):
                break
            details.append(words)
        property_lines = [column(words, PROPERTY, MUNICIPALITY) for words in details]
        property_lines = [line for line in property_lines if line]
        city = next((CITY_LINE.match(line) for line in property_lines if CITY_LINE.match(line)), None)
        street = next((WARD.sub("", line) for line in property_lines if not CITY_LINE.match(line)), None)
        status, when = status_of(status_text, sale_day)
        found.append({
            "case": case, "sale_type": column(header, SALE_TYPE, STATUS), "status_text": status_text,
            "status": status, "sale_date": when, "opening_bid": float(bid.group(1).replace(",", "")) if bid else None,
            "street": street, "city": city.group(1).title() if city else None, "zip_code": city.group(2) if city else None,
            "municipality": " ".join(column(words, MUNICIPALITY, PARCEL) for words in details).strip() or None,
            "parcel": " ".join(column(words, PARCEL, 1000) for words in details).strip() or None,
            "attorney": " ".join(column(words, ATTORNEY, DEFENDANT) for words in details).strip() or None,
        })
    return found


def read_list(pdf_bytes: bytes) -> list[dict]:
    rows = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        sale_day = None
        for page in pdf.pages:
            lines = words_by_line(page)
            text = " ".join(t for _, words in lines[:6] for _, t in words)
            heading = SALE_DAY.search(text)
            if heading:
                sale_day = datetime.strptime(heading.group(1), "%B %d, %Y").date()
            if sale_day:
                rows += blocks(lines, sale_day)
    return rows


def record(row: dict, url: str) -> dict:
    """A record in scrape_pa_sale_listing's shape (RawSheriffSale), without the parties."""
    address = f"{row['street']} {row['city']}, PA {row['zip_code']}" if row["zip_code"] else (row["street"] or "")
    return {"county": "Allegheny", "state": "PA", "sheriff_number": row["case"], "address": address,
            "sale_date": row["sale_date"].isoformat(), "status": row["status"], "upset_price": row["opening_bid"],
            "source_url": url,
            "raw_payload": {"sale_type": row["sale_type"], "raw_status": row["status_text"],
                            "township": row["municipality"], "parcel_number": row["parcel"], "attorney": row["attorney"],
                            "minimum_bid": row["opening_bid"]},
            "plaintiff": None, "defendant": None, "judgment_amount": None, "court_case_number": row["case"]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    records: dict[str, dict] = {}
    with PoliteClient(ScrapingSettings.from_env()) as client:
        page = client.get(PAGE)
        page.raise_for_status()
        links = list(dict.fromkeys(LIST_LINK.findall(page.text)))
        if not links:
            raise SystemExit(f"No sale list linked on {PAGE}; previous snapshot kept")
        for url in links:
            response = client.get(url)
            response.raise_for_status()
            for row in read_list(response.content):
                if row["sale_date"] >= date.today() and row["street"]:
                    records[row["case"]] = record(row, url)
    if not records:
        raise SystemExit("Allegheny: no upcoming sales read; previous snapshot kept")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(sorted(records.values(), key=lambda r: r["sheriff_number"]), indent=2) + "\n")
    print(f"Allegheny: {len(records)} upcoming sales from {len(links)} list(s) -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
