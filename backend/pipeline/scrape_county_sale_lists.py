"""Scrape county foreclosure sale lists published directly by the selling office.

Kentucky, Jefferson County (Louisville): the Jefferson Circuit Court Commissioner's
  upcoming-sales table, served as a CSV (master commissioner judicial sales).
Oklahoma, Oklahoma County: the Sheriff's sales on Bid4Assets (one grid per sale date).
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
OK_OKLAHOMA_URL = "https://www.bid4assets.com/OKCSheriff"
WI_DANE_URL = "https://danesheriff.com/Sales"
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


def parse_bid4assets_rows(rows):
    records = []
    for row in rows:
        address = " ".join(str(row.get("Address") or "").split())
        street, _, city = address.partition(",")
        records.append({
            "case": str(row.get("CourtCase") or row.get("SheriffNumber") or row["AuctionID"]).strip(),
            "auction_id": row["AuctionID"], "sale_date": row["SaleDate"][:10],
            "street": street.strip(), "city": city.strip().title() or None, "zip_code": None,
            "minimum_bid": row.get("MinimumBid"), "plaintiff": row.get("Plaintiff"),
            "defendant": row.get("Defendant"), "attorney": row.get("Attorney"),
            "auction_status": row.get("AuctionStatusString"), "stayed": bool(row.get("IsStayed")),
            "postponed": bool(row.get("IsPostponed")), "raw": row})
    return records


def scrape_ok_oklahoma(client):
    first = client.get(OK_OKLAHOMA_URL)
    first.raise_for_status()
    rows = {}
    for sale_date in MonroeBid4AssetsAdapter._sale_dates(first.text):
        response = client.get(OK_OKLAHOMA_URL, params={"salesdate": sale_date})
        response.raise_for_status()
        for row in MonroeBid4AssetsAdapter._grid_rows(response.text):
            rows[row["AuctionID"]] = row
        time.sleep(1)
    return parse_bid4assets_rows(rows.values()), OK_OKLAHOMA_URL


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


COUNTIES = {("KY", "Jefferson"): scrape_ky_jefferson, ("OK", "Oklahoma"): scrape_ok_oklahoma,
            ("WI", "Dane"): scrape_wi_dane}


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
