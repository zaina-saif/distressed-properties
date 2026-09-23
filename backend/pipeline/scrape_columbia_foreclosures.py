"""Collect the official Columbia County upcoming foreclosure-sale list."""
from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

SOURCE_URL = "https://columbiaclerk.com/clerk-services/foreclosures/upcoming-foreclosure-sales/"
SOURCE_SYSTEM = "fl_columbia_clerk_foreclosure"
OUTPUT = Path("data/sheriff_sales/columbia_foreclosure_sales.json")


def _labels(container) -> dict[str, str]:
    fields: dict[str, str] = {}
    for label in container.select("label"):
        parent = label.parent
        value = parent.select_one("strong, a") if parent else None
        if value:
            fields[label.get_text(" ", strip=True).lower()] = value.get_text(" ", strip=True)
    return fields


def _split_parties(value: str) -> tuple[str | None, str | None]:
    parts = re.split(r"\s+VS\.?\s+", value, maxsplit=1, flags=re.I)
    return (parts[0].strip() or None, parts[1].strip() or None) if len(parts) == 2 else (value or None, None)


def parse_page(html: str, checked: date | None = None) -> dict:
    checked = checked or date.today()
    soup = BeautifulSoup(html, "html.parser")
    page_text = soup.get_text(" ", strip=True)
    revised_match = re.search(r"REVISED:\s*(\d{2}/\d{2}/\d{4})", page_text, re.I)
    revised = datetime.strptime(revised_match.group(1), "%m/%d/%Y").date().isoformat() if revised_match else None
    records = []
    for container in soup.select("div.w-full.grid.md\\:grid-cols-3"):
        fields = _labels(container)
        required = {"status", "sale date", "case number", "judgement amount", "parties", "address", "parcel id"}
        if not required.issubset(fields):
            continue
        case_number = fields["case number"].strip()
        year_match = re.match(r"(20\d{2})", case_number)
        plaintiff, defendant = _split_parties(fields["parties"])
        amount = Decimal(re.sub(r"[^0-9.]", "", fields["judgement amount"]))
        records.append({
            "source_system": SOURCE_SYSTEM,
            "source_url": SOURCE_URL,
            "state": "FL",
            "county": "Columbia",
            "status": fields["status"].lower(),
            "sale_date": datetime.strptime(fields["sale date"], "%m/%d/%Y").date().isoformat(),
            "court_case_number": case_number,
            "judgment_amount": str(amount.quantize(Decimal("0.01"))),
            "plaintiff": plaintiff,
            "defendant": defendant,
            "street_address": fields["address"],
            "parcel_id": fields["parcel id"],
            "distress_start_date": None,
            "distress_start_year": int(year_match.group(1)) if year_match else None,
            "distress_start_basis": "Court case year; exact filing date unavailable from sale listing" if year_match else None,
        })
    records.sort(key=lambda row: (row["sale_date"], row["court_case_number"]))
    return {
        "source_index_url": SOURCE_URL,
        "source_checked_date": checked.isoformat(),
        "source_revised_date": revised,
        "coverage_note": "Official upcoming foreclosure-sale list. Duration is bounded by the case year unless an exact filing date is later obtained.",
        "records": records,
    }


def collect() -> dict:
    with httpx.Client(timeout=30, follow_redirects=True, headers={
        "User-Agent": "nj-sheriff-sale-platform/1.0 (public-record research)"
    }) as client:
        response = client.get(SOURCE_URL)
        response.raise_for_status()
    return parse_page(response.text)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-html", type=Path)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    snapshot = parse_page(args.input_html.read_text()) if args.input_html else collect()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, indent=2) + "\n")
    print(json.dumps({"records": len(snapshot["records"]), "output": str(args.output)}))


if __name__ == "__main__":
    main()

