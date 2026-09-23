"""Load manually verified clerk judgments, preserving date and source."""
from __future__ import annotations

import argparse
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text

from app.database.session import engine
from pipeline.scrape_hillsborough_foreclosure_notices import OUTPUT as NOTICES

DEFAULT_INPUT = Path("data/sheriff_sales/hillsborough_verified_judgments.json")
SOURCE_PREFIX = "https://publicaccess.hillsclerk.com/PAVDirectSearch/"


def validate(records: list[dict], notices: list[dict]) -> None:
    known = {(n["court_case_number"].upper(), n["street_address"].upper(), n["zip_code"])
             for n in notices}
    seen = set()
    for record in records:
        key = (record["court_case_number"].upper(), record["street_address"].upper(),
               record["zip_code"])
        if key not in known:
            raise ValueError(f"Judgment does not match an imported notice: {key}")
        if key in seen:
            raise ValueError(f"Duplicate verified judgment: {key}")
        seen.add(key)
        if Decimal(record["judgment_amount"]) <= 0:
            raise ValueError("Judgment must be positive")
        if date.fromisoformat(record["judgment_amount_as_of_date"]) > date.today():
            raise ValueError("Judgment date in future")
        if not record["source_url"].startswith(SOURCE_PREFIX):
            raise ValueError("Judgment requires clerk source")


def load(path: Path = DEFAULT_INPUT, notices_path: Path = NOTICES) -> int:
    records = json.loads(path.read_text())["records"]
    notices = json.loads(notices_path.read_text())["records"]
    validate(records, notices)
    with engine.begin() as connection:
        for record in records:
            result = connection.execute(text("""UPDATE sheriff_sales AS ss SET
                judgment_amount=:amount,
                judgment_amount_as_of_date=:as_of,
                judgment_source_url=:url,
                updated_at=NOW()
                FROM properties AS p
                WHERE ss.property_id=p.id AND ss.state='FL' AND ss.county='Hillsborough'
                  AND ss.source_system='fl_hillsborough_published_foreclosure_notice'
                  AND ss.court_case_number=:case_number
                  AND UPPER(p.street_address)=:street AND p.zip_code=:zip"""),
                {"amount": Decimal(record["judgment_amount"]),
                 "as_of": record["judgment_amount_as_of_date"],
                 "url": record["source_url"],
                 "case_number": record["court_case_number"],
                 "street": record["street_address"].upper(),
                 "zip": record["zip_code"]})
            if result.rowcount != 1:
                raise ValueError(f"Expected exactly one matching sale for {record['court_case_number']}; got {result.rowcount}")
    return len(records)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    args = parser.parse_args()
    print(json.dumps({"judgments_loaded": load(args.input)}))


if __name__ == "__main__":
    main()
