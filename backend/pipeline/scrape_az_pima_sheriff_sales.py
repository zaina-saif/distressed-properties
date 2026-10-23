"""Pima County, AZ sheriff's sales of real property from the Sheriff's notices of sale.

The Pima County Sheriff's Civil Enforcement page (pimasheriff.org/services/civil-enforcement)
links one "Notice of Sale" PDF per case ("2026: 11/03 Notice of Sale (C20254504)"). Each
notice has a text layer: court case number, the writ (usually a special execution on an
HOA or other judgment), the judgment sum, the property address ("... Property Location:")
and the sale day ("on the 3rd day of November, 2026"). Party names are not kept. Sales
are subject to the owner's statutory right of redemption.

    python -m pipeline.scrape_az_pima_sheriff_sales
    python -m pipeline.load_az_pima_sheriff_sales
"""
import argparse
import html
import io
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

from pypdf import PdfReader

from pipeline.scraping.config import ScrapingSettings
from pipeline.scraping.http import PoliteClient

PAGE = "https://pimasheriff.org/services/civil-enforcement"
OUTPUT = Path("data/sheriff_sales/az_pima_sheriff_sales.json")
PARSER_VERSION = "az_pima_notice_of_sale_v1"
NOTICE_LINK = re.compile(r'href="(https://(?:www\.)?pimasheriff\.org/download_file/\d+/\d+)"[^>]*>\s*([^<]*Notice of Sale[^<]*)<')
CASE = re.compile(r"\((C\d{6,})\)")
ADDRESS = re.compile(r"([0-9][^\n]*?),?\s+AZ,?\s+(\d{5})\s+Property Location:")
SALE_DAY = re.compile(r"on the (\d{1,2})(?:st|nd|rd|th) day\s+of ([A-Z][a-z]+),? (\d{4})")
JUDGMENT = re.compile(r"judgment sum\s+of \$([\d,]+\.\d{2})")
WRIT = re.compile(r"WRIT OF ([A-Z ]+?) issued", re.S)


CITY_ZIP = re.compile(r"^([A-Za-z][A-Za-z .'-]+),\s*AZ,?\s+(\d{5})$", re.I)


def address_of(text: str) -> tuple[str, str, str] | None:
    """Street, city and ZIP from the lines just above "Property Location:": either one line
    ("1984 West Nava Drive Tucson, AZ, 85746") or two ("4698 W. Beeplant Wy" / "Tucson, AZ 85741")."""
    lines = [line.strip() for line in text.split("Property Location:")[0].splitlines() if line.strip()]
    if len(lines) >= 2 and (city := CITY_ZIP.match(lines[-1])) and re.match(r"\d", lines[-2]):
        return " ".join(lines[-2].split()), city.group(1).title(), city.group(2)
    single = ADDRESS.search(text)
    if not single:
        return None
    line = " ".join(single.group(1).split())
    # "1984 West Nava Drive Tucson" -> the city is the last word(s) before AZ.
    match = re.match(r"(.+?)\s+((?:South |North |Oro |Green |Marana|Sahuarita|Tucson|Vail|Catalina|Ajo|Arivaca|Sells)"
                     r"[A-Za-z ]*)$", line)
    street, city = (match.group(1), match.group(2).strip()) if match else (line, "Tucson")
    return street, city, single.group(2)


def notice_from(text: str) -> dict | None:
    flat = " ".join(text.split())
    address, day = address_of(text), SALE_DAY.search(flat)
    if not address or not day:
        return None
    street, city, zip_code = address
    judgment = JUDGMENT.search(flat)
    writ = WRIT.search(flat)
    return {"street": street, "city": city, "zip_code": zip_code,
            "sale_date": datetime.strptime(f"{day.group(1)} {day.group(2)} {day.group(3)}", "%d %B %Y").date().isoformat(),
            "judgment": float(judgment.group(1).replace(",", "")) if judgment else None,
            "writ": f"writ of {writ.group(1).strip().lower()}" if writ else None}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    today, sales, unread = date.today(), [], []
    with PoliteClient(ScrapingSettings.from_env()) as client:
        page = client.get(PAGE)
        page.raise_for_status()
        for url, title in NOTICE_LINK.findall(page.text):
            case = CASE.search(html.unescape(title))
            response = client.get(url)
            response.raise_for_status()
            text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(response.content)).pages)
            notice = notice_from(text)
            if notice is None or not case:
                unread.append(title.strip())
                continue
            if notice["sale_date"] >= today.isoformat():
                sales.append({"case": case.group(1), "notice_url": url, **notice})
    snapshot = {"source_system": "az_pima_sheriff_sale", "state": "AZ", "county": "Pima", "source_url": PAGE,
                "scraped_at": datetime.now(timezone.utc).isoformat(), "parser_version": PARSER_VERSION,
                "sales": sorted(sales, key=lambda sale: (sale["sale_date"], sale["case"])), "unread": unread}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, indent=1) + "\n")
    print(f"Pima: {len(sales)} upcoming sales, {len(unread)} notices not read -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
