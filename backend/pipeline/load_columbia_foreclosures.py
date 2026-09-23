"""Import official Columbia County foreclosure sales into the operational DB."""
from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import text

from app.database.session import engine
from pipeline.scrape_columbia_foreclosures import OUTPUT, SOURCE_SYSTEM, SOURCE_URL


def validate(snapshot: dict, today: date | None = None) -> list[dict]:
    if snapshot.get("source_index_url") != SOURCE_URL:
        raise ValueError("Unexpected source index")
    if date.fromisoformat(snapshot["source_checked_date"]) > (today or date.today()):
        raise ValueError("Source check date is in the future")
    seen = set()
    for record in snapshot["records"]:
        if record.get("source_system") != SOURCE_SYSTEM or record.get("county") != "Columbia":
            raise ValueError("Wrong source or jurisdiction")
        required = ("court_case_number", "sale_date", "street_address", "parcel_id", "defendant", "judgment_amount")
        if any(record.get(field) in (None, "") for field in required):
            raise ValueError("Required foreclosure field missing")
        if record["court_case_number"] in seen:
            raise ValueError("Duplicate case number")
        seen.add(record["court_case_number"])
    return snapshot["records"]


def load(path: Path = OUTPUT) -> dict[str, int]:
    records = validate(json.loads(path.read_text()))
    run_id, now = str(uuid.uuid4()), datetime.now(timezone.utc)
    created = updated = 0
    with engine.begin() as connection:
        connection.execute(text("""INSERT INTO scrape_runs
            (id,job_name,county,source_system,started_at,status,records_found)
            VALUES(:id,:source,'Columbia',:source,:now,'running',:count)"""),
            {"id": run_id, "source": SOURCE_SYSTEM, "now": now, "count": len(records)})
        for record in records:
            case = record["court_case_number"].upper()
            number = "COLUMBIA-FC-" + hashlib.sha256(case.encode()).hexdigest()[:16]
            address_hash = hashlib.sha256(
                f"FL|COLUMBIA|{record['street_address'].upper()}|{record['parcel_id'].upper()}".encode()
            ).hexdigest()
            normalized = f"{record['street_address']}, Columbia County, FL"
            property_id = connection.execute(text("""INSERT INTO properties
                (id,normalized_address,street_address,city,municipality,county,state,zip_code,
                 address_hash,data_quality_score)
                VALUES(:id,:address,:street,'Columbia County','Columbia County','Columbia','FL',NULL,:hash,55)
                ON CONFLICT(address_hash) DO UPDATE SET normalized_address=EXCLUDED.normalized_address,
                    street_address=EXCLUDED.street_address,updated_at=NOW() RETURNING id"""),
                {"id": str(uuid.uuid4()), "address": normalized, "street": record["street_address"], "hash": address_hash}).scalar_one()
            payload = json.dumps(record, sort_keys=True)
            content_hash = hashlib.sha256(payload.encode()).hexdigest()
            connection.execute(text("""INSERT INTO raw_scrape_records
                (id,scrape_run_id,state,county,source_record_id,source_url,raw_payload,
                 content_hash,parsing_status,scraped_at)
                VALUES(:id,:run,'FL','Columbia',:number,:url,CAST(:payload AS JSONB),
                       :hash,'parsed',:now) ON CONFLICT DO NOTHING"""),
                {"id": str(uuid.uuid4()), "run": run_id, "number": number, "url": SOURCE_URL,
                 "payload": payload, "hash": content_hash, "now": now})
            existing = connection.execute(text("""SELECT id FROM sheriff_sales
                WHERE state='FL' AND source_system=:source AND sheriff_number=:number"""),
                {"source": SOURCE_SYSTEM, "number": number}).scalar()
            params = {"id": existing or str(uuid.uuid4()), "property_id": property_id, "number": number,
                      "case": record["court_case_number"], "plaintiff": record["plaintiff"],
                      "defendant": record["defendant"], "sale_date": record["sale_date"],
                      "status": record["status"], "judgment": record["judgment_amount"],
                      "parcel": record["parcel_id"], "start_date": record.get("distress_start_date"),
                      "start_year": record.get("distress_start_year"), "basis": record.get("distress_start_basis"),
                      "url": SOURCE_URL, "now": now, "hash": content_hash, "source": SOURCE_SYSTEM}
            if existing:
                connection.execute(text("""UPDATE sheriff_sales SET property_id=:property_id,
                    court_case_number=:case,plaintiff=:plaintiff,defendant=:defendant,
                    current_sale_date=:sale_date,current_status=:status,judgment_amount=:judgment,
                    judgment_source_url=:url,property_number=:parcel,distress_start_date=:start_date,
                    distress_start_year=:start_year,distress_start_basis=:basis,source_url=:url,
                    last_seen_at=:now,last_scraped_at=:now,raw_source_hash=:hash,is_active=TRUE,updated_at=NOW()
                    WHERE id=:id"""), params)
                updated += 1
            else:
                connection.execute(text("""INSERT INTO sheriff_sales
                    (id,property_id,state,county,sheriff_number,court_case_number,plaintiff,defendant,
                     current_sale_date,current_status,judgment_amount,judgment_source_url,property_number,
                     distress_start_date,distress_start_year,distress_start_basis,source_url,source_system,
                     first_seen_at,last_seen_at,last_scraped_at,raw_source_hash,is_active)
                    VALUES(:id,:property_id,'FL','Columbia',:number,:case,:plaintiff,:defendant,
                     :sale_date,:status,:judgment,:url,:parcel,:start_date,:start_year,:basis,:url,:source,
                     :now,:now,:now,:hash,TRUE)"""), params)
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

