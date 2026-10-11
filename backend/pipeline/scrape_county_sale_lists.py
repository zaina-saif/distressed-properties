"""Scrape county foreclosure sale lists published directly by the selling office.

Kentucky, Jefferson County (Louisville): the Jefferson Circuit Court Commissioner's
  upcoming-sales table, served as a CSV (master commissioner judicial sales).
Oklahoma, Oklahoma County and Wisconsin, Milwaukee County: the Sheriffs' sales on
  Bid4Assets (one grid per sale date, plus each auction's page for the full address).
Oklahoma, Tulsa County: the Sheriff's public Auction Listings Report on Tinstar.
South Dakota, Minnehaha County: the Sheriff's upcoming mortgage foreclosure list (text).
Wisconsin, Dane County: the Sheriff's foreclosure sale list and each sale's detail page.

Each list holds every upcoming sale for its county, so loading retires sales that drop off.

    python -m pipeline.scrape_county_sale_lists --all
"""
import argparse
import csv
import io
import json
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from pipeline.adapters.pa_monroe_bid4assets import MonroeBid4AssetsAdapter

OUTPUT = Path("data/sheriff_sales/county_sale_lists")
PARSER_VERSION = "county_sale_lists_v1"
HEADERS = MonroeBid4AssetsAdapter.HEADERS
KY_JEFFERSON_PAGE = "https://www.jeffcomm.org/upcoming-sales.php"
KY_JEFFERSON_CSV = "https://www.jeffcomm.org/docs/webPush.csv"
BID4ASSETS = {("OK", "Oklahoma"): "https://www.bid4assets.com/OKCSheriff",
              ("WI", "Milwaukee"): "https://www.bid4assets.com/milwaukeesheriffsales"}
OK_TULSA_PAGE = "https://tcso.org/resources/property-auctions/"
OK_TULSA_API = "https://www.tinstar.io/api/cases"
# The endpoint returns every case with internal fields, including buyers' contact
# details; only what the public report shows is kept, and nothing else is saved.
TULSA_FIELDS = ("caseNumber", "variantTag", "saleDate", "plaintiff", "defendant", "address", "city", "zipCode",
                "attorney", "appraisedValue", "salePrice", "recalled", "noSale", "noBid")
TULSA_LOOKBACK_DAYS = 21
WI_DANE_URL = "https://danesheriff.com/Sales"
SD_MINNEHAHA_URL = "https://www.minnehahacounty.gov/dept/so/mortgageForeclosures/mortgageForeclosures.php"
# The county's server refuses requests that do not accept HTML.
HTML_ACCEPT = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
MINNEHAHA_CITIES = ("Sioux Falls", "Brandon", "Hartford", "Dell Rapids", "Baltic", "Colton", "Crooks", "Garretson",
                    "Humboldt", "Renner", "Valley Springs", "Sherman", "Corson", "Lyons", "Rowena", "Ellis", "Harrisburg")
MINNEHAHA_DATE = re.compile(r"^[A-Z][a-z]+day,\s+([A-Z][a-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?,\s+(\d{4})$")
MINNEHAHA_SALE = re.compile(
    r"^(49CIV\S*)\s+(.+?)\s+VS\.?\s+(.+?)\s*\(([^)]*)\)\.?\s+(\d.+?)\s+"
    r"(SFSD|(" + "|".join(city.upper() for city in MINNEHAHA_CITIES) + r"),?\s*SD)\s+(\d{5})\.?\s+"
    r"JUDGMENT\s+AMT\s+(\$[\d,]+(?:\.\d+)?)", re.I)
CITY_LINE = re.compile(r"^(?:CITY OF |VILLAGE OF |TOWN OF )?(.+?),?\s+WI\s+(\d{5})", re.I)


def split_style(style):
    """'PLAINTIFF vs. DEFENDANT, ET AL.' -> (plaintiff, defendant)."""
    parts = re.split(r"\s+vs?\.\s+", style or "", maxsplit=1, flags=re.I)
    clean = [" ".join(part.split()) or None for part in parts]
    return (clean[0], clean[1]) if len(clean) == 2 else (clean[0], None)


def parse_ky_jefferson(text):
    records = []
    for row in csv.DictReader(io.StringIO(text)):
        address = " ".join((row.get("exp4") or "").split())
        match = re.match(r"(.+?)\s+(\d{5})$", address)
        plaintiff, defendant = split_style(row.get("expr5"))
        # A case selling several parcels lists each with a COUNT number.
        count = (row.get("COUNT") or "").strip()
        records.append({
            "case": row["CASE"].strip().upper() + (f"-{count}" if count else ""),
            "court_case": row["CASE"].strip().upper(), "division": row.get("DIV"),
            "sale_date": datetime.strptime(row["Expr1"].strip(), "%m/%d/%Y").date().isoformat(),
            "street": match.group(1) if match else address, "city": "Louisville",
            "zip_code": match.group(2) if match else None, "plaintiff": plaintiff, "defendant": defendant,
            "attorney": " ".join((row.get("ATTORNEY") or "").split()) or None, "docket": row.get("NewDocket"),
            "withdrawn": (row.get("Expr3") or "").strip().upper() == "WITHDRAWN", "raw": row})
    return records


def scrape_ky_jefferson(client):
    response = client.get(KY_JEFFERSON_CSV)
    response.raise_for_status()
    return parse_ky_jefferson(response.content.decode("utf-8-sig", "replace")), KY_JEFFERSON_PAGE


def split_detail_address(street, full):
    """City and ZIP from an auction page's full address, given the grid's street:
    ('4129 N Sherman Blvd', '4129 N Sherman Blvd Milwaukee, WI 53216') -> ('Milwaukee', '53216')."""
    full = " ".join((full or "").split())
    rest = full[len(street):] if street and full.upper().startswith(street.upper()) else ""
    match = re.match(r"\s*,?\s*([A-Za-z .'-]+?),\s*[A-Z]{2}\s+(\d{5})", rest)
    return (match.group(1).strip().title(), match.group(2)) if match else (None, None)


def parse_bid4assets_rows(rows, details=None):
    """details maps AuctionID to the address on its auction page, when fetched."""
    records = []
    for row in rows:
        address = " ".join(str(row.get("Address") or "").split())
        street, _, city = address.partition(",")
        street = street.strip()
        detail_city, zip_code = split_detail_address(street, (details or {}).get(row["AuctionID"]))
        # Without an attorney-set minimum the grid shows a $1 placeholder.
        minimum = row.get("MinimumBid") if row.get("AttorneyHasSetMinBid") and (row.get("MinimumBid") or 0) > 1 else None
        records.append({
            "case": str(row.get("CourtCase") or row.get("SheriffNumber") or row["AuctionID"]).strip(),
            "auction_id": row["AuctionID"], "sale_date": row["SaleDate"][:10],
            "street": street, "city": city.strip().title() or detail_city, "zip_code": zip_code,
            "parcel": row.get("Apn") or None, "minimum_bid": minimum, "plaintiff": row.get("Plaintiff"),
            "defendant": row.get("Defendant"), "attorney": row.get("Attorney"),
            "auction_status": row.get("AuctionStatusString"), "stayed": bool(row.get("IsStayed")),
            "postponed": bool(row.get("IsPostponed")), "raw": row})
    return records


def bid4assets_scraper(state, county):
    url = BID4ASSETS[(state, county)]

    def scrape(client):
        first = client.get(url)
        first.raise_for_status()
        rows = {}
        for sale_date in MonroeBid4AssetsAdapter._sale_dates(first.text):
            response = client.get(url, params={"salesdate": sale_date})
            response.raise_for_status()
            for row in MonroeBid4AssetsAdapter._grid_rows(response.text):
                rows[row["AuctionID"]] = row
            time.sleep(1)
        details = {}
        # Only Milwaukee's grid leaves out the city; Oklahoma County's pages add no ZIP.
        for auction_id in [key for key, row in rows.items() if "," not in str(row.get("Address") or "")]:
            response = client.get(f"https://www.bid4assets.com/auction/index/{auction_id}")
            if response.is_success:
                details[auction_id] = MonroeBid4AssetsAdapter._detail_address(response.text)
            time.sleep(1)
        return parse_bid4assets_rows(rows.values(), details), url
    return scrape


def parse_tulsa_cases(cases, today):
    """Cases the public report would list: not hidden, with a sale date from
    TULSA_LOOKBACK_DAYS ago onward (recent results included)."""
    records = []
    for case in cases:
        sale_date = case.get("saleDate") or ""
        if case.get("status") != "complete" or case.get("hideFromReports") or not re.match(r"\d{4}-\d{2}-\d{2}$", sale_date):
            continue
        if (today - date.fromisoformat(sale_date)).days > TULSA_LOOKBACK_DAYS:
            continue
        kept = {field: case.get(field) for field in TULSA_FIELDS}
        variant = (kept["variantTag"] or "").strip()
        # Staff sometimes prefix the address with a note ("recalled!! 8516 E. 23RD PL").
        address = " ".join((kept["address"] or "").split())
        note = re.match(r"^\W*(recalled|cancel+ed|withdrawn)\W*\s*", address, re.I)
        if note:
            address = address[note.end():]
        records.append({
            "case": kept["caseNumber"].strip().upper() + (f"-{variant}" if variant else ""),
            "sale_date": sale_date, "street": address,
            "city": (kept["city"] or "").strip().title() or None, "zip_code": (kept["zipCode"] or "").strip()[:5] or None,
            "plaintiff": kept["plaintiff"], "defendant": kept["defendant"], "attorney": kept["attorney"],
            "appraised_value": kept["appraisedValue"], "sale_price": kept["salePrice"],
            "recalled": bool(kept["recalled"] or note), "no_sale": bool(kept["noSale"]), "no_bid": bool(kept["noBid"]),
            "raw": kept})
    return records


def scrape_ok_tulsa(client):
    response = client.get(OK_TULSA_API, headers={"Referer": "https://www.tinstar.io/reports"})
    response.raise_for_status()
    return parse_tulsa_cases(response.json(), date.today()), OK_TULSA_PAGE


def parse_minnehaha(html):
    """Sales under 'Upcoming Scheduled Mortgage Foreclosures', grouped by a date heading;
    returns (records, lines that look like sales but did not parse)."""
    text = BeautifulSoup(html, "html.parser").get_text("\n")
    lines = [" ".join(line.split()) for line in text.splitlines()]
    start = next((i for i, line in enumerate(lines) if line.startswith("Upcoming Scheduled Mortgage Foreclosures")), None)
    records, unparsed, sale_date = [], [], None
    for line in lines[start:] if start is not None else []:
        if line.startswith("Minnehaha County Sheriff") and "Procedure" in line:
            break
        heading = MINNEHAHA_DATE.match(line)
        if heading:
            sale_date = datetime.strptime(" ".join(heading.groups()), "%B %d %Y").date().isoformat()
            continue
        if not line.upper().startswith("49CIV") or not sale_date:
            continue
        match = MINNEHAHA_SALE.match(line)
        if not match:
            unparsed.append(line)
            continue
        case, plaintiff, defendant, attorney, street, place, city, zip_code, judgment = match.groups()
        street = street.rstrip(" .,")
        # One listing omits its case number ("49CIV FREEDOM ..."); key it by address.
        key = case.upper() if re.search(r"\d", case[5:]) else f"49CIV-{street.upper()}"
        records.append({"case": key, "court_case": case.upper() if key == case.upper() else None,
                        "sale_date": sale_date, "street": street, "city": city.title() if city else "Sioux Falls",
                        "zip_code": zip_code, "plaintiff": plaintiff.strip(), "defendant": defendant.strip(),
                        "attorney": attorney.strip() or None, "judgment": judgment, "raw": line})
    return records, unparsed


def scrape_sd_minnehaha(client):
    response = client.get(SD_MINNEHAHA_URL, headers=HTML_ACCEPT)
    response.raise_for_status()
    records, unparsed = parse_minnehaha(response.text)
    for line in unparsed:
        print(f"SD Minnehaha: could not parse: {line[:60]}...")
    return records, SD_MINNEHAHA_URL


def parse_dane_list(html):
    """(detail URL, sale date, case, street, city, ZIP, status) for each listed sale."""
    rows = []
    table = BeautifulSoup(html, "html.parser").find("table", id="tblSales")
    for tr in table.find("tbody").find_all("tr") if table else []:
        cells = tr.find_all("td")
        if len(cells) < 5:
            continue
        lines = [" ".join(line.split()) for line in cells[3].stripped_strings]
        city = CITY_LINE.match(lines[1]) if len(lines) > 1 else None
        rows.append({
            "detail_url": "https://danesheriff.com" + cells[0].find("a")["href"],
            "sale_date": datetime.strptime(cells[1].get_text(strip=True), "%m/%d/%Y").date().isoformat(),
            "case": cells[2].get_text(strip=True), "street": lines[0] if lines else "",
            "city": city.group(1).strip().title() if city else None, "zip_code": city.group(2) if city else None,
            "list_status": cells[4].get_text(strip=True)})
    return rows


def parse_dane_detail(html):
    """The 'Sale Details' table: one label cell and one value cell per row."""
    soup = BeautifulSoup(html, "html.parser")
    fields = {}
    for tr in soup.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) == 2:
            fields[cells[0].get_text(" ", strip=True)] = " ".join(cells[1].get_text(" ", strip=True).split())
    notice = soup.find("a", href=re.compile(r"/Sales/GetNotice/\d+"))
    fields["notice_url"] = "https://danesheriff.com" + notice["href"] if notice else None
    return fields


def scrape_wi_dane(client):
    page = client.get(WI_DANE_URL)
    page.raise_for_status()
    records = []
    for row in parse_dane_list(page.text):
        detail = client.get(row["detail_url"])
        detail.raise_for_status()
        fields = parse_dane_detail(detail.text)
        records.append({**row, "sale_number": fields.get("Sale #"), "municipality": fields.get("Municipality"),
                        "plaintiff": fields.get("Plaintiff"), "defendant": fields.get("Defendant"),
                        "attorney": fields.get("Plaintiff's Attorney"), "opening_bid": fields.get("Opening Bid"),
                        "notice_url": fields.get("notice_url"), "raw": fields})
        time.sleep(1)
    return records, WI_DANE_URL


COUNTIES = {("KY", "Jefferson"): scrape_ky_jefferson, ("OK", "Oklahoma"): bid4assets_scraper("OK", "Oklahoma"),
            ("OK", "Tulsa"): scrape_ok_tulsa, ("SD", "Minnehaha"): scrape_sd_minnehaha, ("WI", "Dane"): scrape_wi_dane,
            ("WI", "Milwaukee"): bid4assets_scraper("WI", "Milwaukee")}


def snapshot_path(state, county):
    return OUTPUT / f"{state.lower()}_{county.lower()}.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--counties", nargs="+", metavar="ST:County", help="e.g. KY:Jefferson OK:Oklahoma")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    keys = sorted(COUNTIES) if args.all else [tuple(value.split(":", 1)) for value in args.counties or []]
    OUTPUT.mkdir(parents=True, exist_ok=True)
    failed = []
    with httpx.Client(headers=HEADERS, timeout=60, follow_redirects=True) as client:
        for state, county in keys:
            try:
                records, url = COUNTIES[(state, county)](client)
            except Exception as exc:  # noqa: BLE001 - keep the previous snapshot
                print(f"{state} {county}: FAILED, previous snapshot kept ({type(exc).__name__}: {exc})")
                failed.append(f"{state}:{county}")
                continue
            if not records:
                print(f"{state} {county}: FAILED, the list was empty; previous snapshot kept")
                failed.append(f"{state}:{county}")
                continue
            snapshot_path(state, county).write_text(json.dumps({
                "state": state, "county": county, "source_url": url, "parser_version": PARSER_VERSION,
                "scraped_at": datetime.now(timezone.utc).isoformat(), "records": records}, indent=1, default=str) + "\n")
            print(f"{state} {county}: {len(records)} sales")
    if failed:
        raise SystemExit(f"Failed counties: {', '.join(failed)}")


if __name__ == "__main__":
    main()
