"""Load real-estate-only Palm Beach sheriff execution sales."""
from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import text

from app.database.session import engine
from pipeline.scrape_palm_beach_sheriff_real_estate import OUTPUT, SOURCE_SYSTEM, VENDOR_URL


def validate(snapshot: dict, today: date | None = None) -> list[dict]:
    if snapshot.get("source_index_url") != VENDOR_URL:
        raise ValueError("Unexpected auction source")
    if date.fromisoformat(snapshot["source_checked_date"]) > (today or date.today()):
        raise ValueError("Source check date is in the future")
    seen = set()
    for row in snapshot["records"]:
        required = ("court_case_number", "street_address", "city", "zip_code", "defendant", "sale_date", "writ_issued_date")
        if row.get("source_system") != SOURCE_SYSTEM or any(not row.get(field) for field in required):
            raise ValueError("Incomplete Palm Beach real-estate record")
        if "real property" not in row["notice_text"].lower():
            raise ValueError("Non-real-estate record rejected")
        if row["court_case_number"] in seen:
            raise ValueError("Duplicate case")
        seen.add(row["court_case_number"])
    return snapshot["records"]


def load(path: Path = OUTPUT) -> dict[str, int]:
    records = validate(json.loads(path.read_text()))
    run_id, now = str(uuid.uuid4()), datetime.now(timezone.utc)
    created = updated = 0
    with engine.begin() as connection:
        connection.execute(text("""INSERT INTO scrape_runs
            (id,job_name,county,source_system,started_at,status,records_found)
            VALUES(:id,:source,'Palm Beach',:source,:now,'running',:count)"""),
            {"id": run_id, "source": SOURCE_SYSTEM, "now": now, "count": len(records)})
        for row in records:
            case = row["court_case_number"].upper()
            number = "PALMBEACH-SHERIFF-" + hashlib.sha256(case.encode()).hexdigest()[:16]
            normalized = f"{row['street_address']}, {row['city']}, FL {row['zip_code']}"
            address_hash = hashlib.sha256(f"FL|PALM BEACH|{normalized.upper()}".encode()).hexdigest()
            property_id = connection.execute(text("""INSERT INTO properties
                (id,normalized_address,street_address,city,municipality,county,state,zip_code,address_hash,data_quality_score)
                VALUES(:id,:address,:street,:city,:city,'Palm Beach','FL',:zip,:hash,70)
                ON CONFLICT(address_hash) DO UPDATE SET normalized_address=EXCLUDED.normalized_address,
                  street_address=EXCLUDED.street_address,city=EXCLUDED.city,zip_code=EXCLUDED.zip_code,
                  updated_at=NOW() RETURNING id"""),
                {"id": str(uuid.uuid4()), "address": normalized, "street": row["street_address"],
                 "city": row["city"], "zip": row["zip_code"], "hash": address_hash}).scalar_one()
            payload = json.dumps(row, sort_keys=True)
            content_hash = hashlib.sha256(payload.encode()).hexdigest()
            connection.execute(text("""INSERT INTO raw_scrape_records
                (id,scrape_run_id,state,county,source_record_id,source_url,raw_payload,content_hash,parsing_status,scraped_at)
                VALUES(:id,:run,'FL','Palm Beach',:number,:url,CAST(:payload AS JSONB),:hash,'parsed',:now)
                ON CONFLICT DO NOTHING"""), {"id": str(uuid.uuid4()), "run": run_id, "number": number,
                "url": row["source_url"], "payload": payload, "hash": content_hash, "now": now})
            existing = connection.execute(text("""SELECT id FROM sheriff_sales
                WHERE state='FL' AND source_system=:source AND sheriff_number=:number"""),
                {"source": SOURCE_SYSTEM, "number": number}).scalar()
            params = {"id": existing or str(uuid.uuid4()), "property_id": property_id, "number": number,
                      "case": row["court_case_number"], "plaintiff": row["plaintiff"], "defendant": row["defendant"],
                      "sale_date": row["sale_date"], "description": row["interest_offered"] + ". " + (row["legal_description"] or ""),
                      "start": row["distress_start_date"], "year": row["distress_start_year"],
                      "basis": row["distress_start_basis"], "url": row["source_url"], "now": now,
                      "hash": content_hash, "source": SOURCE_SYSTEM}
            if existing:
                connection.execute(text("""UPDATE sheriff_sales SET property_id=:property_id,court_case_number=:case,
                  plaintiff=:plaintiff,defendant=:defendant,current_sale_date=:sale_date,current_status='scheduled',
                  judgment_amount=NULL,description_text=:description,distress_start_date=:start,
                  distress_start_year=:year,distress_start_basis=:basis,source_url=:url,last_seen_at=:now,
                  last_scraped_at=:now,raw_source_hash=:hash,is_active=TRUE,updated_at=NOW() WHERE id=:id"""), params)
                updated += 1
            else:
                connection.execute(text("""INSERT INTO sheriff_sales
                  (id,property_id,state,county,sheriff_number,court_case_number,plaintiff,defendant,
                   current_sale_date,current_status,judgment_amount,description_text,distress_start_date,
                   distress_start_year,distress_start_basis,source_url,source_system,first_seen_at,last_seen_at,
                   last_scraped_at,raw_source_hash,is_active)
                  VALUES(:id,:property_id,'FL','Palm Beach',:number,:case,:plaintiff,:defendant,:sale_date,
                   'scheduled',NULL,:description,:start,:year,:basis,:url,:source,:now,:now,:now,:hash,TRUE)"""), params)
                created += 1
        connection.execute(text("""UPDATE scrape_runs SET completed_at=NOW(),status='completed',
          records_created=:created,records_updated=:updated WHERE id=:id"""),
          {"created": created, "updated": updated, "id": run_id})
    return {"created": created, "updated": updated, "total": len(records)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=OUTPUT)
    args = parser.parse_args()
    print(json.dumps(load(args.input)))


if __name__ == "__main__":
    main()

