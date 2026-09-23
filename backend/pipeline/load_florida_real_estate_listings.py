"""Import public Florida government real-estate sale listings."""
from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import text

from app.database.session import engine
from pipeline.scrape_florida_real_estate_listings import OUTPUT

ALLOWED_SOURCES = {
    "fl_fdot_surplus_property", "fl_swfwmd_land_for_sale", "fl_us_treasury_real_property"
}


def validate(snapshot: dict, today: date | None = None) -> list[dict]:
    if date.fromisoformat(snapshot["source_checked_date"]) > (today or date.today()):
        raise ValueError("Source check date is in the future")
    records = snapshot["records"]
    seen = set()
    for row in records:
        if row.get("source_system") not in ALLOWED_SOURCES or row.get("state") != "FL":
            raise ValueError("Unexpected Florida listing source")
        if any(not row.get(key) for key in ("record_id", "county", "street_address", "city", "normalized_address")):
            raise ValueError("Incomplete Florida property listing")
        if row["record_id"] in seen:
            raise ValueError("Duplicate source record")
        seen.add(row["record_id"])
    return records


def load(path: Path = OUTPUT) -> dict[str, int]:
    records = validate(json.loads(path.read_text()))
    run_id, now = str(uuid.uuid4()), datetime.now(timezone.utc)
    created = updated = 0
    with engine.begin() as connection:
        connection.execute(text("""INSERT INTO scrape_runs
            (id,job_name,county,source_system,started_at,status,records_found)
            VALUES(:id,'Florida real-estate listings','Florida','fl_public_real_estate',:now,'running',:count)"""),
            {"id": run_id, "now": now, "count": len(records)})
        for row in records:
            source = row["source_system"]
            number = row["record_id"].upper().replace(":", "-")
            address_hash = hashlib.sha256(
                f"FL|{row['county'].upper()}|{row['record_id'].upper()}".encode()
            ).hexdigest()
            property_id = connection.execute(text("""INSERT INTO properties
                (id,normalized_address,street_address,city,municipality,county,state,zip_code,
                 property_type,bedrooms,bathrooms,square_feet,acreage,year_built,latitude,longitude,
                 address_hash,data_quality_score)
                VALUES(:id,:address,:street,:city,:city,:county,'FL',:zip,:type,:beds,:baths,:sqft,
                       :acreage,:year,:lat,:lon,:hash,:quality)
                ON CONFLICT(address_hash) DO UPDATE SET normalized_address=EXCLUDED.normalized_address,
                    street_address=EXCLUDED.street_address,city=EXCLUDED.city,zip_code=EXCLUDED.zip_code,
                    property_type=COALESCE(EXCLUDED.property_type,properties.property_type),
                    bedrooms=COALESCE(EXCLUDED.bedrooms,properties.bedrooms),
                    bathrooms=COALESCE(EXCLUDED.bathrooms,properties.bathrooms),
                    square_feet=COALESCE(EXCLUDED.square_feet,properties.square_feet),
                    acreage=COALESCE(EXCLUDED.acreage,properties.acreage),
                    year_built=COALESCE(EXCLUDED.year_built,properties.year_built),
                    latitude=COALESCE(EXCLUDED.latitude,properties.latitude),
                    longitude=COALESCE(EXCLUDED.longitude,properties.longitude),updated_at=NOW()
                RETURNING id"""), {"id": str(uuid.uuid4()), "address": row["normalized_address"],
                "street": row["street_address"], "city": row["city"], "county": row["county"],
                "zip": row.get("zip_code"), "type": row.get("property_type"), "beds": row.get("bedrooms"),
                "baths": row.get("bathrooms"), "sqft": row.get("square_feet"), "acreage": row.get("acreage"),
                "year": row.get("year_built"), "lat": row.get("latitude"), "lon": row.get("longitude"),
                "hash": address_hash, "quality": 75 if row.get("zip_code") else 45}).scalar_one()
            raw = json.dumps(row, sort_keys=True)
            content_hash = hashlib.sha256(raw.encode()).hexdigest()
            connection.execute(text("""INSERT INTO raw_scrape_records
                (id,scrape_run_id,state,county,source_record_id,source_url,raw_payload,content_hash,parsing_status,scraped_at)
                VALUES(:id,:run,'FL',:county,:number,:url,CAST(:payload AS JSONB),:hash,'parsed',:now)
                ON CONFLICT DO NOTHING"""), {"id": str(uuid.uuid4()), "run": run_id,
                "county": row["county"], "number": number, "url": row["source_url"],
                "payload": raw, "hash": content_hash, "now": now})
            existing = connection.execute(text("""SELECT id FROM sheriff_sales
                WHERE state='FL' AND source_system=:source AND sheriff_number=:number"""),
                {"source": source, "number": number}).scalar()
            params = {"id": existing or str(uuid.uuid4()), "property_id": property_id, "number": number,
                "county": row["county"], "date": row.get("sale_date"), "status": row.get("current_status", "listed"),
                "description": row.get("listing_description"), "url": row["source_url"], "source": source,
                "starting_bid": row.get("starting_bid"), "parcel": row.get("property_number"),
                "now": now, "hash": content_hash}
            if existing:
                connection.execute(text("""UPDATE sheriff_sales SET property_id=:property_id,county=:county,
                    current_sale_date=:date,current_status=:status,description_text=:description,
                    source_url=:url,starting_bid=:starting_bid,property_number=:parcel,
                    last_seen_at=:now,last_scraped_at=:now,raw_source_hash=:hash,is_active=TRUE,updated_at=NOW()
                    WHERE id=:id"""), params)
                updated += 1
            else:
                connection.execute(text("""INSERT INTO sheriff_sales
                    (id,property_id,state,county,sheriff_number,current_sale_date,current_status,starting_bid,
                     description_text,property_number,source_url,source_system,first_seen_at,last_seen_at,
                     last_scraped_at,raw_source_hash,is_active)
                    VALUES(:id,:property_id,'FL',:county,:number,:date,:status,:starting_bid,:description,
                     :parcel,:url,:source,:now,:now,:now,:hash,TRUE)"""), params)
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

