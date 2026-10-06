"""Scrape South Carolina Master-in-Equity foreclosure sale lists.

Charleston: the Master's running auction list (one HTML table for upcoming sales).
Greenville: the Greenville Journal's per-sale-date list for the Master in Equity.
Richland's page answers "Access Denied" to scripts, so it is not collected.

Lists fill in shortly before each monthly sale.

    python -m pipeline.scrape_sc_master_in_equity --all
"""
import argparse
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

OUTPUT = Path("data/sheriff_sales/sc_master_in_equity")
PARSER_VERSION = "sc_master_in_equity_v1"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"}
CHARLESTON_URL = "https://www.charlestoncounty.gov/foreclosure/runninglist.html"
GREENVILLE_PAGE = "https://mie.greenvillejournal.com/printer-friendly-sale-list/"
GREENVILLE_LIST = "https://mie.greenvillejournal.com/wp-content/plugins/master-in-equity/download-clerk-docs.php"
# Charleston lists an area, not a mailing city; these areas are inside the City of Charleston.
CHARLESTON_AREAS = {"west ashley": "Charleston", "downtown charleston": "Charleston", "james island": "Charleston",
                    "johns island": "Charleston", "daniel island": "Charleston", "mt. pleasant": "Mount Pleasant",
                    "mt pleasant": "Mount Pleasant"}


def cells(row):
    return [" ".join(cell.get_text(" ", strip=True).split()) for cell in row.find_all(["td", "th"])]


def parse_charleston(html):
    records = []
    for row in BeautifulSoup(html, "html.parser").find_all("tr"):
        values = cells(row)
        if len(values) < 8:
            continue
        match = re.match(r"(\d{2})-(\d{2})-(\d{2})\s+(\S+)", values[0])
        if not match:
            continue
        month, day, year, case = match.groups()
        tms = re.findall(r"\b\d{10}\b", values[3])
        street = re.sub(r"\b\d{10}\b", " ", values[3]).strip()
        area = values[7].strip()
        records.append({
            "case": case, "sale_date": date(2000 + int(year), int(month), int(day)).isoformat(),
            "plaintiff": values[1] or None, "defendant": values[2] or None,
            "street": " ".join(street.split()), "city": CHARLESTON_AREAS.get(area.lower(), area) or None,
            "zip_code": None, "parcel": ", ".join(tms) or None, "judgment": values[4] or None,
            "lien": values[5] or None, "attorney": values[6] or None, "withdrawn": False, "raw": values})
    return records


def parse_greenville(html, sale_date):
    records = []
    for row in BeautifulSoup(html, "html.parser").find_all("tr"):
        tds = row.find_all("td")
        if len(tds) < 11:
            continue
        values = cells(row)
        address_lines = list(tds[6].stripped_strings)
        street = address_lines[0] if address_lines else ""
        city_line = address_lines[1] if len(address_lines) > 1 else ""
        city = re.match(r"\s*([^,]+),\s*SC\s*(\d{5})?", city_line)
        records.append({
            "case": values[5], "sale_date": sale_date.isoformat(), "plaintiff": values[9] or None,
            "defendant": values[10] or None, "street": " ".join(street.split()),
            "city": city.group(1).strip().title() if city else None, "zip_code": city.group(2) if city else None,
            "parcel": None, "judgment": None, "lien": None,
            "attorney": " / ".join(value for value in values[7:9] if value) or None,
            # The first column marks a withdrawn case.
            "withdrawn": bool(values[0]), "sale_number": values[4], "comments": values[11] if len(values) > 11 else None,
            "raw": values})
    return records


def scrape_charleston(client):
    response = client.get(CHARLESTON_URL)
    response.raise_for_status()
    # The list is exported from Word in Windows-1252.
    return parse_charleston(response.content.decode("windows-1252", "replace")), CHARLESTON_URL


def scrape_greenville(client):
    page = client.get(GREENVILLE_PAGE)
    page.raise_for_status()
    dates = sorted({datetime.strptime(value, "%m/%d/%Y").date()
                    for value in re.findall(r"\b(\d{2}/\d{2}/\d{4})\b", page.text)})
    records = []
    for sale_date in (d for d in dates if d >= date.today()):
        response = client.post(GREENVILLE_LIST, data={"closedate": sale_date.strftime("%m/%d/%Y"),
                                                      "target": "Generate List"})
        response.raise_for_status()
        records.extend(parse_greenville(response.text, sale_date))
    return records, GREENVILLE_PAGE


COUNTIES = {"Charleston": scrape_charleston, "Greenville": scrape_greenville}


def snapshot_path(county):
    return OUTPUT / f"sc_{county.lower()}.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--counties", nargs="+", choices=sorted(COUNTIES))
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    failed = []
    with httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True) as client:
        for county in sorted(COUNTIES) if args.all else args.counties or []:
            try:
                records, url = COUNTIES[county](client)
            except Exception as exc:  # noqa: BLE001 - keep the previous snapshot
                print(f"SC {county}: FAILED, previous snapshot kept ({type(exc).__name__}: {exc})")
                failed.append(county)
                continue
            snapshot_path(county).write_text(json.dumps({
                "state": "SC", "county": county, "source_url": url, "parser_version": PARSER_VERSION,
                "scraped_at": datetime.now(timezone.utc).isoformat(), "records": records}, indent=1) + "\n")
            print(f"SC {county}: {len(records)} sales")
    if failed:
        raise SystemExit(f"Failed counties: {', '.join(failed)}")


if __name__ == "__main__":
    main()
