"""Import published Hillsborough foreclosure notices as unverified auctions."""
from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import text

from app.database.session import engine
from pipeline.scrape_hillsborough_foreclosure_notices import OUTPUT

SOURCE_SYSTEM = "fl_hillsborough_published_foreclosure_notice"


def validate(snapshot: dict, today: date | None = None) -> list[dict]:
    if snapshot.get("source_index_url") != "https://legals.businessobserverfl.com/news/hillsborough/":
        raise ValueError("Unexpected source index")
    if date.fromisoformat(snapshot["source_checked_date"]) > (today or date.today()):
        raise ValueError("Source check date is in the future")
    seen = set()
    for record in snapshot["records"]:
        if record["state"] != "FL" or record["county"] != "Hillsborough":
            raise ValueError("Wrong jurisdiction")
        if record["source_system"] != SOURCE_SYSTEM or not record["source_url"].startswith("https://legals.businessobserverfl.com/news/"):
            raise ValueError("Wrong source")
        if not record["street_address"] or not record["court_case_number"]:
            raise ValueError("Address and case number required")
        if date.fromisoformat(record["sale_date"]) < (today or date.today()):
            raise ValueError("Past sale in current snapshot")
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
            VALUES(:id,:source,'Hillsborough',:source,:now,'running',:count)"""),
            {"id": run_id, "source": SOURCE_SYSTEM, "now": now, "count": len(records)})
        for record in records:
            case = record["court_case_number"].upper()
            number = "HILLS-FC-" + hashlib.sha256(case.encode()).hexdigest()[:16]
            address_hash = hashlib.sha256(f"FL|Hillsborough|{record['street_address'].upper()}|{record['zip_code']}".encode()).hexdigest()
            property_id = connection.execute(text("""INSERT INTO properties
                (id,normalized_address,street_address,city,municipality,county,state,zip_code,
                 address_hash,data_quality_score)
                VALUES(:id,:address,:street,:city,:city,'Hillsborough','FL',:zip,:hash,60)
                ON CONFLICT(address_hash) DO UPDATE SET
                    normalized_address=EXCLUDED.normalized_address,
                    street_address=EXCLUDED.street_address,city=EXCLUDED.city,
                    zip_code=EXCLUDED.zip_code,updated_at=NOW() RETURNING id"""),
                {"id": str(uuid.uuid4()), "address": record["address"],
                 "street": record["street_address"], "city": record["city"],
                 "zip": record["zip_code"], "hash": address_hash}).scalar_one()
            payload = json.dumps(record, sort_keys=True)
            content_hash = hashlib.sha256(payload.encode()).hexdigest()
            connection.execute(text("""INSERT INTO raw_scrape_records
                (id,scrape_run_id,state,county,source_record_id,source_url,raw_payload,
                 content_hash,parsing_status,scraped_at)
                VALUES(:id,:run,'FL','Hillsborough',:number,:url,CAST(:payload AS JSONB),
                       :hash,'partial',:now) ON CONFLICT DO NOTHING"""),
                {"id": str(uuid.uuid4()), "run": run_id, "number": number,
                 "url": record["source_url"], "payload": payload,
                 "hash": content_hash, "now": now})
            existing = connection.execute(text("""SELECT id FROM sheriff_sales
                WHERE state='FL' AND source_system=:source AND sheriff_number=:number"""),
                {"source": SOURCE_SYSTEM, "number": number}).scalar()
            params = {"id": existing or str(uuid.uuid4()), "property_id": property_id,
                      "number": number, "case": record["court_case_number"],
                      "sale_date": record["sale_date"], "url": record["source_url"],
                      "description": "Published foreclosure auction notice " + record["notice_id"] +
                          " (" + (record["publication_date"] or "publication date unavailable") +
                          "); sale/cancellation status not verified against clerk calendar. Full notice retained in raw scrape record.",
                      "now": now, "hash": content_hash, "source": SOURCE_SYSTEM}
            if existing:
                connection.execute(text("""UPDATE sheriff_sales SET
                    property_id=:property_id,court_case_number=:case,
                    current_sale_date=:sale_date,
                    current_status=CASE WHEN current_status IN ('scheduled_unverified','date_passed_unverified')
                        THEN 'scheduled_unverified' ELSE current_status END,
                    description_text=:description,source_url=:url,last_seen_at=:now,
                    last_scraped_at=:now,raw_source_hash=:hash,is_active=TRUE,updated_at=NOW()
                    WHERE id=:id"""), params)
                updated += 1
            else:
                connection.execute(text("""INSERT INTO sheriff_sales
                    (id,property_id,state,county,sheriff_number,court_case_number,
                     current_sale_date,current_status,description_text,source_url,source_system,
                     first_seen_at,last_seen_at,last_scraped_at,raw_source_hash,is_active)
                    VALUES(:id,:property_id,'FL','Hillsborough',:number,:case,:sale_date,
                           'scheduled_unverified',:description,:url,:source,:now,:now,:now,:hash,TRUE)"""), params)
                created += 1
        connection.execute(text("""UPDATE sheriff_sales SET
            current_status='date_passed_unverified',is_active=FALSE,updated_at=NOW()
            WHERE source_system=:source AND current_status='scheduled_unverified'
              AND current_sale_date<CURRENT_DATE"""), {"source": SOURCE_SYSTEM})
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
