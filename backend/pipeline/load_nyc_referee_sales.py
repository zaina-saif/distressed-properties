"""Load source-labeled NYC NYCTL referee auctions into the operational list."""
from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import text

from app.database.session import engine
from pipeline.scrape_nyc_referee_sales import COUNTIES_BY_BBL, DEFAULT_OUTPUT, SOURCE_URL

SOURCE_SYSTEM = "nyc_nyctl_referee_sales"


def validate(records: list[dict], today: date | None = None) -> None:
    seen = set()
    cutoff = today or date.today()
    for record in records:
        bbl = record["bbl"]
        if record["county"] != COUNTIES_BY_BBL.get(bbl[0]):
            raise ValueError(f"County does not match BBL: {bbl}")
        if bbl in seen:
            raise ValueError(f"Duplicate BBL in current NYCTL listing: {bbl}")
        seen.add(bbl)
        if not record["street_address"] or not record["sale_date"]:
            raise ValueError(f"Missing address or sale date: {bbl}")
        if date.fromisoformat(record["sale_date"]) < cutoff:
            raise ValueError(f"Past auction date in current snapshot: {bbl}")


def load(path: Path = DEFAULT_OUTPUT) -> dict[str, int]:
    records = json.loads(path.read_text())
    validate(records)
    run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    created = updated = 0
    with engine.begin() as connection:
        connection.execute(text("""INSERT INTO scrape_runs
            (id,job_name,source_system,started_at,status,records_found)
            VALUES(:id,'nyc_nyctl_referee_sales',:source,:now,'running',:count)"""),
            {"id": run_id, "source": SOURCE_SYSTEM, "now": now, "count": len(records)})
        for record in records:
            county, bbl = record["county"], record["bbl"]
            address_hash = hashlib.sha256(f"NY|{county}|BBL|{bbl}".encode()).hexdigest()
            property_id = connection.execute(text("""INSERT INTO properties
                (id,normalized_address,street_address,city,municipality,county,state,zip_code,
                 latitude,longitude,property_type,address_hash,data_quality_score)
                VALUES(:id,:address,:street,:city,:city,:county,'NY',:zip,:latitude,:longitude,
                       :property_type,:hash,75)
                ON CONFLICT(address_hash) DO UPDATE SET
                  normalized_address=EXCLUDED.normalized_address,
                  street_address=EXCLUDED.street_address,city=EXCLUDED.city,
                  zip_code=EXCLUDED.zip_code,
                  latitude=COALESCE(EXCLUDED.latitude,properties.latitude),
                  longitude=COALESCE(EXCLUDED.longitude,properties.longitude),
                  property_type=EXCLUDED.property_type,updated_at=NOW()
                RETURNING id"""),
                {"id": str(uuid.uuid4()), "address": record["address"],
                 "street": record["street_address"], "city": record["city"],
                 "county": county, "zip": record.get("zip_code"),
                 "latitude": record.get("latitude"), "longitude": record.get("longitude"),
                 "property_type": record.get("building_class"), "hash": address_hash}).scalar_one()
            payload = json.dumps(record, sort_keys=True)
            content_hash = hashlib.sha256(payload.encode()).hexdigest()
            number = f"NYCTL-{bbl}"
            connection.execute(text("""INSERT INTO raw_scrape_records
                (id,scrape_run_id,state,county,source_record_id,source_url,raw_payload,
                 content_hash,parsing_status,scraped_at)
                VALUES(:id,:run,'NY',:county,:number,:url,CAST(:payload AS JSONB),
                       :hash,'parsed',:now) ON CONFLICT DO NOTHING"""),
                {"id": str(uuid.uuid4()), "run": run_id, "county": county,
                 "number": number, "url": SOURCE_URL, "payload": payload,
                 "hash": content_hash, "now": now})
            existing = connection.execute(text("""SELECT id FROM sheriff_sales
                WHERE state='NY' AND source_system=:source AND sheriff_number=:number"""),
                {"source": SOURCE_SYSTEM, "number": number}).scalar()
            params = {"id": existing or str(uuid.uuid4()), "property_id": property_id,
                      "county": county, "number": number, "sale_date": record["sale_date"],
                      "upset": record.get("upset_price"), "description": record.get("details"),
                      "now": now, "hash": content_hash, "url": SOURCE_URL,
                      "source": SOURCE_SYSTEM, "bbl": bbl}
            if existing:
                connection.execute(text("""UPDATE sheriff_sales SET
                  property_id=:property_id,current_sale_date=:sale_date,current_status='scheduled',
                  upset_price=:upset,description_text=:description,source_url=:url,
                  property_number=:bbl,last_seen_at=:now,last_scraped_at=:now,
                  raw_source_hash=:hash,is_active=TRUE,updated_at=NOW()
                  WHERE id=:id"""), params)
                updated += 1
            else:
                connection.execute(text("""INSERT INTO sheriff_sales
                  (id,property_id,state,county,sheriff_number,current_sale_date,current_status,
                   upset_price,description_text,source_url,source_system,property_number,
                   first_seen_at,last_seen_at,last_scraped_at,raw_source_hash,is_active)
                  VALUES(:id,:property_id,'NY',:county,:number,:sale_date,'scheduled',
                         :upset,:description,:url,:source,:bbl,:now,:now,:now,:hash,TRUE)"""), params)
                created += 1
        connection.execute(text("""UPDATE sheriff_sales SET
            current_status='date_passed_unverified',is_active=FALSE,updated_at=NOW()
            WHERE state='NY' AND source_system=:source
              AND current_status='scheduled' AND current_sale_date<CURRENT_DATE"""),
            {"source": SOURCE_SYSTEM})
        connection.execute(text("""UPDATE scrape_runs SET completed_at=NOW(),status='completed',
            records_created=:created,records_updated=:updated WHERE id=:id"""),
            {"created": created, "updated": updated, "id": run_id})
    return {"created": created, "updated": updated, "total": len(records)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(load(args.input)))


if __name__ == "__main__":
    main()
