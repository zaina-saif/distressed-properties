"""Import the Kings County court's address-indexed foreclosure notices.

The PDF index and court page establish an advertised address and auction date,
but not a BBL, case number, judgment, or sale result. PDF contents were not
accessible during the initial import and must be enriched separately.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import text

from app.database.session import engine

SOURCE_SYSTEM = "nyc_kings_court_foreclosure_index"
DEFAULT_INPUT = Path("data/sheriff_sales/nyc_kings_court_foreclosure_index.json")


def parse_snapshot(snapshot: dict, today: date | None = None) -> list[dict]:
    sale_date = date.fromisoformat(snapshot["sale_date"])
    if date.fromisoformat(snapshot["source_checked_date"]) > (today or date.today()):
        raise ValueError("Snapshot check date is in the future")
    directory = snapshot["source_directory_url"]
    if not directory.startswith("https://www.nycourts.gov/"):
        raise ValueError("Expected an official court directory")
    filenames = snapshot["notice_filenames"]
    if len(filenames) != len(set(filenames)):
        raise ValueError("Duplicate notice filename")
    records = []
    for filename in filenames:
        if not filename.endswith(".pdf") or "/" in filename or ".." in filename:
            raise ValueError(f"Invalid notice filename: {filename}")
        address = filename[:-4].strip()
        if not address or not address[0].isdigit():
            raise ValueError(f"Missing address in notice filename: {filename}")
        source_url = directory + quote(filename)
        number = "KINGS-" + sale_date.strftime("%Y%m%d") + "-" + hashlib.sha256(filename.encode()).hexdigest()[:12]
        records.append({
            "source_system": SOURCE_SYSTEM,
            "source_url": source_url,
            "source_page_url": snapshot["source_page_url"],
            "sheriff_number": number,
            "sale_type": "Court foreclosure auction",
            "sale_date": sale_date.isoformat(),
            "sale_time": snapshot["sale_time"],
            "sale_location": snapshot["sale_location"],
            "county": "Kings", "state": "NY", "city": "Brooklyn",
            "address": f"{address}, Brooklyn, NY",
            "street_address": address,
            "court_case_number": None, "bbl": None,
            "plaintiff": None, "defendant": None,
            "judgment_amount": None, "upset_price": None, "sale_result": None,
            "notes": "Address from official PDF filename; auction date from court page. PDF contents and current sale status not independently verified.",
        })
    return records


def load(path: Path = DEFAULT_INPUT) -> dict[str, int]:
    records = parse_snapshot(json.loads(path.read_text()))
    now = datetime.now(timezone.utc)
    run_id = str(uuid.uuid4())
    created = updated = 0
    with engine.begin() as connection:
        connection.execute(text("""INSERT INTO scrape_runs
            (id,job_name,county,source_system,started_at,status,records_found)
            VALUES(:id,'nyc_kings_court_foreclosure_index','Kings',:source,:now,'running',:count)"""),
            {"id": run_id, "source": SOURCE_SYSTEM, "now": now, "count": len(records)})
        for record in records:
            number = record["sheriff_number"]
            address_hash = hashlib.sha256(f"NY|Kings|COURT-PDF|{record['source_url']}".encode()).hexdigest()
            property_id = connection.execute(text("""INSERT INTO properties
                (id,normalized_address,street_address,city,municipality,county,state,
                 address_hash,data_quality_score)
                VALUES(:id,:address,:street,'Brooklyn','Brooklyn','Kings','NY',:hash,50)
                ON CONFLICT(address_hash) DO UPDATE SET
                    normalized_address=EXCLUDED.normalized_address,
                    street_address=EXCLUDED.street_address,updated_at=NOW()
                RETURNING id"""),
                {"id": str(uuid.uuid4()), "address": record["address"],
                 "street": record["street_address"], "hash": address_hash}).scalar_one()
            payload = json.dumps(record, sort_keys=True)
            content_hash = hashlib.sha256(payload.encode()).hexdigest()
            connection.execute(text("""INSERT INTO raw_scrape_records
                (id,scrape_run_id,state,county,source_record_id,source_url,raw_payload,
                 content_hash,parsing_status,scraped_at)
                VALUES(:id,:run,'NY','Kings',:number,:url,CAST(:payload AS JSONB),
                       :hash,'partial',:now) ON CONFLICT DO NOTHING"""),
                {"id": str(uuid.uuid4()), "run": run_id, "number": number,
                 "url": record["source_url"], "payload": payload,
                 "hash": content_hash, "now": now})
            existing = connection.execute(text("""SELECT id FROM sheriff_sales
                WHERE state='NY' AND county='Kings' AND sheriff_number=:number"""),
                {"number": number}).scalar()
            # A court-calendar listing is not proof the auction will go ahead.
            status = "scheduled_unverified" if date.fromisoformat(record["sale_date"]) >= date.today() else "date_passed_unverified"
            params = {"id": existing or str(uuid.uuid4()), "property_id": property_id,
                      "number": number, "sale_date": record["sale_date"], "status": status,
                      "description": f"{record['sale_type']}; {record['sale_location']}; {record['notes']}",
                      "url": record["source_url"], "source": SOURCE_SYSTEM,
                      "now": now, "hash": content_hash,
                      "active": status == "scheduled_unverified"}
            if existing:
                connection.execute(text("""UPDATE sheriff_sales SET
                    property_id=:property_id,current_sale_date=:sale_date,
                    current_status=CASE WHEN current_status IN
                        ('scheduled_unverified','date_passed_unverified')
                        THEN :status ELSE current_status END,
                    description_text=:description,source_url=:url,last_seen_at=:now,
                    last_scraped_at=:now,raw_source_hash=:hash,
                    is_active=CASE WHEN current_status IN
                        ('scheduled_unverified','date_passed_unverified')
                        THEN :active ELSE is_active END,
                    updated_at=NOW() WHERE id=:id"""), params)
                updated += 1
            else:
                connection.execute(text("""INSERT INTO sheriff_sales
                    (id,property_id,state,county,sheriff_number,current_sale_date,current_status,
                     description_text,source_url,source_system,first_seen_at,last_seen_at,
                     last_scraped_at,raw_source_hash,is_active)
                    VALUES(:id,:property_id,'NY','Kings',:number,:sale_date,:status,
                           :description,:url,:source,:now,:now,:now,:hash,:active)"""), params)
                created += 1
        connection.execute(text("""UPDATE scrape_runs SET completed_at=NOW(),status='completed',
            records_created=:created,records_updated=:updated WHERE id=:id"""),
            {"created": created, "updated": updated, "id": run_id})
    return {"created": created, "updated": updated, "total": len(records)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    args = parser.parse_args()
    print(json.dumps(load(args.input)))


if __name__ == "__main__":
    main()
