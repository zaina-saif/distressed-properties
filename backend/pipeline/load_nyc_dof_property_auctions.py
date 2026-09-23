"""Load source-verified NYC DOF sheriff real-property notices.

The initial snapshot was transcribed from the DOF PDF. A past notice is never
treated as a completed sale or an upcoming auction without a newer source.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import text

from app.database.session import engine

SOURCE_SYSTEM = "nyc_dof_sheriff_property_auctions"
DEFAULT_INPUT = Path("data/sheriff_sales/nyc_dof_property_auctions.json")


def validate(records: list[dict], today: date | None = None) -> None:
    seen: set[str] = set()
    cutoff = today or date.today()
    for record in records:
        number = record["sheriff_number"]
        if number in seen:
            raise ValueError(f"Duplicate sheriff case: {number}")
        seen.add(number)
        if record["source_system"] != SOURCE_SYSTEM or record["state"] != "NY":
            raise ValueError(f"Wrong source or state: {number}")
        if record["county"] != "New York" or not record["bbl"].startswith("1"):
            raise ValueError(f"County and BBL mismatch: {number}")
        if not record["source_url"].startswith("https://www.nyc.gov/"):
            raise ValueError(f"Unofficial notice URL: {number}")
        sale_date = date.fromisoformat(record["sale_date"])
        if sale_date < cutoff and (record["is_active"] or record["current_status"] != "date_passed_unverified"):
            raise ValueError(f"Past notice incorrectly marked active: {number}")
        if record["sale_result"] is None and record["current_status"] == "sold":
            raise ValueError(f"Unverified result marked sold: {number}")


def load(path: Path = DEFAULT_INPUT) -> dict[str, int]:
    records = json.loads(path.read_text())
    validate(records)
    now = datetime.now(timezone.utc)
    run_id = str(uuid.uuid4())
    created = updated = 0
    with engine.begin() as connection:
        connection.execute(text("""INSERT INTO scrape_runs
            (id,job_name,county,source_system,started_at,status,records_found)
            VALUES(:id,'nyc_dof_property_auctions','New York',:source,:now,'running',:count)"""),
            {"id": run_id, "source": SOURCE_SYSTEM, "now": now, "count": len(records)})
        for record in records:
            number = record["sheriff_number"]
            address_hash = hashlib.sha256(f"NY|New York|BBL|{record['bbl']}".encode()).hexdigest()
            property_id = connection.execute(text("""INSERT INTO properties
                (id,normalized_address,street_address,unit_number,city,municipality,county,
                 state,zip_code,property_type,address_hash,data_quality_score)
                VALUES(:id,:address,:street,:unit,:city,:city,'New York','NY',:zip,
                       :property_type,:hash,75)
                ON CONFLICT(address_hash) DO UPDATE SET
                    normalized_address=EXCLUDED.normalized_address,
                    street_address=EXCLUDED.street_address,
                    unit_number=EXCLUDED.unit_number,
                    zip_code=EXCLUDED.zip_code,
                    property_type=EXCLUDED.property_type,
                    updated_at=NOW()
                RETURNING id"""),
                {"id": str(uuid.uuid4()), "address": record["address"],
                 "street": record["street_address"], "unit": record["unit_number"],
                 "city": record["city"], "zip": record["zip_code"],
                 "property_type": record["property_type"], "hash": address_hash}).scalar_one()
            payload = json.dumps(record, sort_keys=True)
            content_hash = hashlib.sha256(payload.encode()).hexdigest()
            connection.execute(text("""INSERT INTO raw_scrape_records
                (id,scrape_run_id,state,county,source_record_id,source_url,raw_payload,
                 content_hash,parsing_status,scraped_at)
                VALUES(:id,:run,'NY','New York',:number,:url,CAST(:payload AS JSONB),
                       :hash,'parsed',:now) ON CONFLICT DO NOTHING"""),
                {"id": str(uuid.uuid4()), "run": run_id, "number": number,
                 "url": record["source_url"], "payload": payload,
                 "hash": content_hash, "now": now})
            existing = connection.execute(text("""SELECT id FROM sheriff_sales
                WHERE state='NY' AND county='New York' AND sheriff_number=:number"""),
                {"number": number}).scalar()
            description = (f"{record['sale_type']}; BBL {record['bbl']}; "
                           f"{record['sale_location']}; {record['payment_terms']}. "
                           f"{record['notes']}")
            params = {"id": existing or str(uuid.uuid4()), "property_id": property_id,
                      "number": number, "sale_date": record["sale_date"],
                      "status": record["current_status"], "plaintiff": record["plaintiff"],
                      "defendant": record["defendant"], "description": description,
                      "url": record["source_url"], "source": SOURCE_SYSTEM,
                      "bbl": record["bbl"], "now": now, "hash": content_hash,
                      "active": record["is_active"]}
            if existing:
                connection.execute(text("""UPDATE sheriff_sales SET
                    property_id=:property_id,current_sale_date=:sale_date,current_status=:status,
                    plaintiff=:plaintiff,defendant=:defendant,description_text=:description,
                    source_url=:url,property_number=:bbl,last_seen_at=:now,
                    last_scraped_at=:now,raw_source_hash=:hash,is_active=:active,
                    updated_at=NOW() WHERE id=:id"""), params)
                updated += 1
            else:
                connection.execute(text("""INSERT INTO sheriff_sales
                    (id,property_id,state,county,sheriff_number,current_sale_date,current_status,
                     plaintiff,defendant,description_text,source_url,source_system,property_number,
                     first_seen_at,last_seen_at,last_scraped_at,raw_source_hash,is_active)
                    VALUES(:id,:property_id,'NY','New York',:number,:sale_date,:status,
                           :plaintiff,:defendant,:description,:url,:source,:bbl,
                           :now,:now,:now,:hash,:active)"""), params)
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
