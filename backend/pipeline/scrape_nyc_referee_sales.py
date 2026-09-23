"""Snapshot public NYCTL referee auction notices for all five NYC boroughs.

These are tax-lien foreclosure referee auctions, not NYC Sheriff executions.
The listing is not a complete foreclosure calendar; absent boroughs stay empty.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

SOURCE_URL = "https://www.tcmfc.com/nyctl-referee-sales"
GEOCODE_URL = "https://geosearch.planninglabs.nyc/v2/search"
DEFAULT_OUTPUT = Path("data/sheriff_sales/nyc_nyctl_referee_sales.json")
COUNTIES_BY_BBL = {"1": "New York", "2": "Bronx", "3": "Kings", "4": "Queens", "5": "Richmond"}
CITIES = {"New York": "New York", "Bronx": "Bronx", "Kings": "Brooklyn",
          "Queens": "Queens", "Richmond": "Staten Island"}
DATE_RE = re.compile(r"(\w+ \d{1,2})(?:st|nd|rd|th)(, \d{4})", re.I)
BBL_RE = re.compile(r"\bBBL:\s*([1-5]-\d{5}-\d{4})\b", re.I)
PRICE_RE = re.compile(r"Upset Price:\s*\$([\d,]+)", re.I)


def parse_listing(html: str, today: date | None = None) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one(".entry-content table")
    if table is None:
        raise ValueError("NYCTL sale table not found; source page layout may have changed")
    rows = table.find_all("tr")
    if len(rows) % 2:
        raise ValueError("NYCTL sale table has an unmatched row")
    records = []
    for heading, detail in zip(rows[::2], rows[1::2]):
        headings = heading.find_all("h3")
        if len(headings) != 2:
            raise ValueError("NYCTL sale heading is missing address or date")
        address = headings[0].get_text(" ", strip=True)
        date_text = headings[1].get_text(" ", strip=True)
        match = DATE_RE.search(date_text)
        bbl_match = BBL_RE.search(detail.get_text(" ", strip=True))
        if not match or not bbl_match:
            raise ValueError(f"NYCTL sale is missing date or BBL: {address}")
        sale_date = datetime.strptime(match.group(1) + match.group(2), "%B %d, %Y").date()
        if today and sale_date < today:
            continue
        bbl = bbl_match.group(1)
        county = COUNTIES_BY_BBL[bbl[0]]
        detail_text = detail.get_text(" ", strip=True)
        price_match = PRICE_RE.search(detail_text)
        zip_match = re.search(r"\b(\d{5})(?:-\d{4})?\s*$", address)
        street = re.split(r",\s*(?:Brooklyn|Bronx|Queens|Manhattan|New York|Staten Island)\b",
                          address, maxsplit=1, flags=re.I)[0].strip()
        if not street:
            raise ValueError(f"NYCTL sale has no street address: {address}")
        records.append({
            "source_id": "nyc_nyctl_referee_sales", "source_url": SOURCE_URL,
            "sale_type": "Referee tax-lien auction", "county": county,
            "city": CITIES[county], "bbl": bbl, "address": address,
            "street_address": street, "zip_code": zip_match.group(1) if zip_match else None,
            "sale_date": sale_date.isoformat(), "sale_time": date_text.split(", ", 2)[-1],
            "upset_price": int(price_match.group(1).replace(",", "")) if price_match else None,
            "building_class": re.search(r"Building Class:\s*(.*)$", detail_text, re.I).group(1).strip()
            if re.search(r"Building Class:\s*(.*)$", detail_text, re.I) else None,
            "details": detail_text,
        })
    return records


def fetch_records(today: date | None = None) -> list[dict]:
    with httpx.Client(timeout=30, follow_redirects=True,
                      headers={"User-Agent": "nj-sheriff-sale-platform/1.0"}) as client:
        response = client.get(SOURCE_URL)
        response.raise_for_status()
        records = parse_listing(response.text, today or date.today())
        for record in records:
            record["latitude"] = record["longitude"] = None
            try:
                geocode = client.get(GEOCODE_URL, params={"text": record["address"], "size": 5})
                geocode.raise_for_status()
                for feature in geocode.json().get("features", []):
                    pad = feature.get("properties", {}).get("addendum", {}).get("pad", {})
                    if str(pad.get("bbl", "")) == record["bbl"].replace("-", ""):
                        record["longitude"], record["latitude"] = feature["geometry"]["coordinates"]
                        break
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                # No coordinate is safer than an unverified address match.
                pass
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    records = fetch_records()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(records, indent=2) + "\n")
    counts = {county: sum(record["county"] == county for record in records)
              for county in COUNTIES_BY_BBL.values()}
    print(json.dumps({"source": SOURCE_URL, "output": str(args.output), "borough_counts": counts}))


if __name__ == "__main__":
    main()
