"""Collect Palm Beach sheriff sales advertised on Bid4Assets, real estate only.

Bid4Assets blocks server-side requests. Florida Public Notices publishes the
underlying legal advertisements and exposes a public JSON search endpoint, so
it is used as the record source while retaining the auction vendor URL.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime
from pathlib import Path

import httpx

SEARCH_URL = "https://floridapublicnotices.com/"
VENDOR_URL = "https://www.bid4assets.com/pbsosheriffsales"
SOURCE_SYSTEM = "fl_palm_beach_sheriff_execution"
OUTPUT = Path("data/sheriff_sales/palm_beach_sheriff_real_estate.json")

CASE_RE = re.compile(r"Case\s*#\s*([A-Z0-9-]+)", re.I)
WRIT_RE = re.compile(r"Writ of Execution.*?on the (\d{1,2})(?:st|nd|rd|th) day of ([A-Za-z]+), (20\d{2})", re.I | re.S)
LEVY_RE = re.compile(r"and on the (\d{1,2})(?:st|nd|rd|th) day of ([A-Za-z]+), (20\d{2}).*?have made levy", re.I | re.S)
PARTIES_RE = re.compile(r"cause wherein,\s*(.*?),\s*Plaintiff and\s*(.*?),\s*Defendant", re.I | re.S)
INTEREST_RE = re.compile(r"All rights, title and interest of\s*(.*?),\s*the within named defendant", re.I | re.S)
ADDRESS_RE = re.compile(r"property may be seen prior to the sale at\s+(.+?\s+FL\s+\d{5})", re.I | re.S)
SALE_RE = re.compile(r"on\s+(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+the\s+(\d{1,2})(?:st|nd|rd|th) day of ([A-Za-z]+), (20\d{2})", re.I)


def _date(match: re.Match[str] | None) -> str | None:
    return datetime.strptime(" ".join(match.groups()), "%d %B %Y").date().isoformat() if match else None


def _clean(value: str) -> str:
    return " ".join(value.split()).strip(" .,;")


def parse_notice(notice: dict) -> dict | None:
    text = notice.get("notice", "")
    # Exclude vehicles and personal property. Require the notice's affirmative
    # description of real property rather than relying on an address alone.
    if not re.search(r"\bREAL PROPERTY\b", text, re.I):
        return None
    case = CASE_RE.search(text)
    parties = PARTIES_RE.search(text)
    address_match = ADDRESS_RE.search(text)
    sale = SALE_RE.search(text)
    if not all((case, parties, address_match, sale)):
        return None
    full_address = _clean(address_match.group(1))
    location = re.match(
        r"(.+?\b(?:STREET|ST|AVENUE|AVE|ROAD|RD|DRIVE|DR|COURT|CT|LANE|LN|"
        r"BOULEVARD|BLVD|TERRACE|TER|PLACE|PL|WAY|CIRCLE|CIR|TRAIL|TRL))\s+"
        r"([A-Z][A-Z ]+),?\s+FL\s+(\d{5})$",
        full_address,
        re.I,
    )
    if not location:
        return None
    description_match = re.search(r"REAL PROPERTY OF THE DEFENDANT LISTED BELOW:\s*(.*?)\s*The property may be seen", text, re.I | re.S)
    interest_match = INTEREST_RE.search(text)
    writ = WRIT_RE.search(text)
    levy = LEVY_RE.search(text)
    notice_id = str(notice["id"])
    return {
        "source_system": SOURCE_SYSTEM,
        "source_url": f"https://floridapublicnotices.com/notices/{notice_id}",
        "auction_url": VENDOR_URL,
        "source_notice_id": notice_id,
        "publication_date": notice.get("date"),
        "state": "FL",
        "county": "Palm Beach",
        "court_case_number": case.group(1),
        "plaintiff": _clean(parties.group(1)),
        "defendant": _clean(parties.group(2)),
        "levied_interest_holder": _clean(interest_match.group(1)) if interest_match else None,
        "interest_offered": "25% undivided interest" if re.search(r"25 PERCENT UNDIVIDED INTEREST", text, re.I) else "Defendant's right, title and interest",
        "writ_issued_date": _date(writ),
        "levy_date": _date(levy),
        "sale_date": _date(sale),
        "street_address": _clean(location.group(1)),
        "city": _clean(location.group(2)).title(),
        "zip_code": location.group(3),
        "legal_description": _clean(description_match.group(1)) if description_match else None,
        "judgment_amount": None,
        "judgment_amount_note": "Not stated in the sheriff-sale notice",
        "distress_start_date": _date(writ),
        "distress_start_year": int(case.group(1)[:4]) if re.match(r"20\d{2}", case.group(1)) else None,
        "distress_start_basis": "Writ of Execution issue date",
        "status": "scheduled",
        "notice_text": text,
    }


def parse_search_response(payload: dict, checked: date | None = None) -> dict:
    notices = payload.get("_embedded", {}).get("notices", [])
    records = [record for notice in notices if (record := parse_notice(notice))]
    records.sort(key=lambda row: (row["sale_date"], row["court_case_number"]))
    return {
        "source_index_url": VENDOR_URL,
        "record_source_url": SEARCH_URL,
        "source_checked_date": (checked or date.today()).isoformat(),
        "coverage_note": "Bid4Assets-linked Palm Beach sheriff notices filtered to explicit real property. Vehicles and other personal property are excluded.",
        "records": records,
    }


def collect(year: int | None = None) -> dict:
    year = year or date.today().year
    query = {"counties": ["50"], "date-range--start-date": f"{year}-01-01",
             "date-range--end-date": f"{year}-12-31", "keywords": "pbsosheriffsales",
             "offset": 0, "paper": "-1", "sort-by": "Newest", "limit": 100}
    with httpx.Client(timeout=45, follow_redirects=True, headers={
        "User-Agent": "nj-sheriff-sale-platform/1.0 (public-record research)"
    }) as client:
        response = client.post(SEARCH_URL, json=query)
        response.raise_for_status()
    return parse_search_response(response.json())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-json", type=Path)
    parser.add_argument("--year", type=int)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    snapshot = parse_search_response(json.loads(args.input_json.read_text())) if args.input_json else collect(args.year)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, indent=2) + "\n")
    print(json.dumps({"records": len(snapshot["records"]), "output": str(args.output)}))


if __name__ == "__main__":
    main()
