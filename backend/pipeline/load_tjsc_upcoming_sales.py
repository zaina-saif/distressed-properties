"""Load the TJSC Illinois upcoming-sales snapshot into the shared sales tables."""
from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

from app.database.session import engine
from pipeline.scrape_tjsc_upcoming_sales import OUTPUT, SOURCE_SYSTEM, SOURCE_URL


def _hash_payload(record: dict) -> str:
    return hashlib.sha256(json.dumps(record, sort_keys=True, default=str).encode()).hexdigest()


def validate(snapshot: dict) -> list[dict]:
    if snapshot.get("source_index_url") != SOURCE_URL or snapshot.get("source_system") != SOURCE_SYSTEM:
        raise ValueError("Unexpected TJSC snapshot source")
    if snapshot.get("state") != "IL":
        raise ValueError("TJSC snapshot is not an Illinois snapshot")
    seen: set[tuple[str, str]] = set()
    for record in snapshot.get("records", []):
        required = ("court_case_number", "street_address", "city", "zip_code")
        if any(record.get(field) in (None, "") for field in required):
            raise ValueError(f"Required TJSC field missing: {required}")
        key = (str(record["court_case_number"]).strip().upper(), str(record["street_address"]).strip().upper())
        if key in seen:
            raise ValueError(f"Duplicate TJSC case/address: {key[0]}")
        seen.add(key)
    return snapshot["records"]


def load(path: Path = OUTPUT) -> dict[str, int]:
    records = validate(json.loads(path.read_text(encoding="utf-8")))
    run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    created = updated = 0
    with engine.begin() as connection:
        # Older snapshots briefly included TJSC's repeated header row. Remove
        # that invalid sale before refreshing the clean snapshot.
        connection.execute(text("""DELETE FROM sheriff_sales
            WHERE state='IL' AND source_system=:source AND court_case_number='Case Number'"""),
            {"source": SOURCE_SYSTEM})
        connection.execute(text("""INSERT INTO scrape_runs
            (id,job_name,county,source_system,started_at,status,records_found)
            VALUES(:id,'il_tjsc_upcoming_sales','Illinois',:source,:now,'running',:count)"""),
            {"id": run_id, "source": SOURCE_SYSTEM, "now": now, "count": len(records)})
        for record in records:
            county = (record.get("county") or "Unknown").strip() or "Unknown"
            street = record["street_address"].strip()
            city = record["city"].strip()
            zip_code = record["zip_code"].strip()
            normalized = f"{street}, {city}, IL {zip_code}"
            address_hash = hashlib.sha256(f"IL|{county.upper()}|{normalized.upper()}".encode()).hexdigest()
            property_id = connection.execute(text("""INSERT INTO properties
                (id,normalized_address,street_address,city,municipality,county,state,zip_code,
                 address_hash,data_quality_score)
                VALUES(:id,:normalized,:street,:city,:city,:county,'IL',:zip,:hash,70)
                ON CONFLICT(address_hash) DO UPDATE SET normalized_address=EXCLUDED.normalized_address,
                    street_address=EXCLUDED.street_address,city=EXCLUDED.city,county=EXCLUDED.county,
                    state='IL',zip_code=EXCLUDED.zip_code,updated_at=NOW() RETURNING id"""),
                {"id": str(uuid.uuid4()), "normalized": normalized, "street": street,
                 "city": city, "county": county, "zip": zip_code, "hash": address_hash}).scalar_one()
            content_hash = _hash_payload(record)
            number_key = f"{record['court_case_number'].upper()}|{street.upper()}|{zip_code}"
            number = "TJSC-IL-" + hashlib.sha256(number_key.encode()).hexdigest()[:16]
            connection.execute(text("""INSERT INTO raw_scrape_records
                (id,scrape_run_id,state,county,source_record_id,source_url,raw_payload,
                 content_hash,parsing_status,scraped_at)
                VALUES(:id,:run,'IL',:county,:source_id,:url,CAST(:payload AS JSONB),
                       :hash,'parsed',:now) ON CONFLICT DO NOTHING"""),
                {"id": str(uuid.uuid4()), "run": run_id, "county": county,
                 "source_id": number, "url": SOURCE_URL,
                 "payload": json.dumps(record), "hash": content_hash, "now": now})
            existing = connection.execute(text("""SELECT id FROM sheriff_sales
                WHERE state='IL' AND source_system=:source AND sheriff_number=:number"""),
                {"source": SOURCE_SYSTEM, "number": number}).scalar()
            params = {"id": existing or str(uuid.uuid4()), "property_id": property_id,
                      "county": county, "number": number, "case": record["court_case_number"],
                      "sale_date": record.get("sale_date"), "status": "scheduled",
                      "upset_price": record.get("opening_bid"), "url": SOURCE_URL,
                      "now": now, "hash": content_hash}
            if existing:
                connection.execute(text("""UPDATE sheriff_sales SET property_id=:property_id,
                    court_case_number=:case,current_sale_date=:sale_date,current_status=:status,
                    upset_price=:upset_price,source_url=:url,last_seen_at=:now,last_scraped_at=:now,
                    raw_source_hash=:hash,is_active=TRUE,updated_at=NOW() WHERE id=:id"""), params)
                updated += 1
            else:
                connection.execute(text("""INSERT INTO sheriff_sales
                    (id,property_id,state,county,sheriff_number,court_case_number,current_sale_date,
                     current_status,upset_price,source_url,source_system,first_seen_at,last_seen_at,
                     last_scraped_at,raw_source_hash,is_active)
                    VALUES(:id,:property_id,'IL',:county,:number,:case,:sale_date,:status,:upset_price,
                     :url,:source,:now,:now,:now,:hash,TRUE)"""), {**params, "source": SOURCE_SYSTEM})
                created += 1
            connection.execute(text("""INSERT INTO sheriff_sale_status_history
                (id,sheriff_sale_id,status,sale_date,upset_price,observed_at,source_url)
                SELECT :history_id,:sale_id,:status,:sale_date,:upset_price,:now,:url
                WHERE NOT EXISTS (SELECT 1 FROM sheriff_sale_status_history
                    WHERE sheriff_sale_id=:sale_id AND status=:status
                    AND sale_date IS NOT DISTINCT FROM :sale_date)"""),
                {"history_id": str(uuid.uuid4()), "sale_id": params["id"], "status": "scheduled",
                 "sale_date": params["sale_date"], "upset_price": params["upset_price"],
                 "now": now, "url": SOURCE_URL})
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
