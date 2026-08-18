"""Load official New York county sheriff-sale snapshots."""
import argparse
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

from app.database.session import engine


FILES = {
    "Erie": Path("data/sheriff_sales/ny_erie_sheriff_sales.json"),
    "Orange": Path("data/sheriff_sales/ny_orange_sheriff_sales.json"),
}


def address_parts(raw: str) -> tuple[str, str, str, str | None]:
    value = " ".join(raw.split())
    match = re.search(r"\bNY\s+(\d{5})(?:-\d{4})?\b", value, re.I)
    zip_code = match.group(1) if match else None
    before = value[:match.start()].strip(" ,") if match else value
    city_match = re.search(r"([A-Za-z][A-Za-z .'-]{1,40}),?$", before)
    city = city_match.group(1).strip() if city_match else "Unknown"
    street = before[:city_match.start()].strip(" ,") if city_match else before
    return value, street, city, zip_code


def load(county: str, path: Path) -> None:
    records = json.loads(path.read_text())
    run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    created = updated = 0
    with engine.begin() as connection:
        connection.execute(text("""INSERT INTO scrape_runs(id,job_name,county,source_system,started_at,status,records_found)
          VALUES(:id,:job,:county,'ny_county_official',:now,'running',:count)"""),
          {"id": run_id, "job": f"ny_{county.lower()}_sheriff_scrape", "county": county,
           "now": now, "count": len(records)})
        for record in records:
            normalized, street, city, zip_code = address_parts(record["address"])
            address_hash = hashlib.sha256(f"NY|{county}|{normalized.upper()}".encode()).hexdigest()
            property_id = connection.execute(text("""INSERT INTO properties(id,normalized_address,street_address,
              city,municipality,county,state,zip_code,address_hash,data_quality_score)
              VALUES(:id,:normalized,:street,:city,:city,:county,'NY',:zip,:hash,65)
              ON CONFLICT(address_hash) DO UPDATE SET updated_at=NOW() RETURNING id"""),
              {"id": str(uuid.uuid4()), "normalized": normalized, "street": street, "city": city,
               "county": county, "zip": zip_code, "hash": address_hash}).scalar_one()
            content_hash = hashlib.sha256(json.dumps(record, sort_keys=True, default=str).encode()).hexdigest()
            connection.execute(text("""INSERT INTO raw_scrape_records(id,scrape_run_id,state,county,
              source_record_id,source_url,raw_payload,content_hash,parsing_status,scraped_at)
              VALUES(:id,:run,'NY',:county,:number,:url,CAST(:payload AS JSONB),:hash,'parsed',:now)
              ON CONFLICT DO NOTHING"""),
              {"id": str(uuid.uuid4()), "run": run_id, "county": county,
               "number": record["sheriff_number"], "url": record["source_url"],
               "payload": json.dumps(record), "hash": content_hash, "now": now})
            existing = connection.execute(text("""SELECT id FROM sheriff_sales
              WHERE state='NY' AND county=:county AND sheriff_number=:number"""),
              {"county": county, "number": record["sheriff_number"]}).scalar()
            params = {"id": existing or str(uuid.uuid4()), "property_id": property_id, "county": county,
                      "number": record["sheriff_number"], "case": record.get("court_case_number"),
                      "plaintiff": record.get("plaintiff"), "defendant": record.get("defendant"),
                      "sale_date": record.get("sale_date"), "status": record.get("status") or "unknown",
                      "judgment": record.get("judgment_amount"), "url": record.get("source_url"),
                      "now": now, "hash": content_hash}
            if existing:
                connection.execute(text("""UPDATE sheriff_sales SET property_id=:property_id,
                  court_case_number=:case,plaintiff=:plaintiff,defendant=:defendant,
                  current_sale_date=:sale_date,current_status=:status,
                  judgment_amount=COALESCE(:judgment,judgment_amount),source_url=:url,
                  last_seen_at=:now,last_scraped_at=:now,raw_source_hash=:hash,updated_at=NOW()
                  WHERE id=:id"""), params)
                updated += 1
            else:
                connection.execute(text("""INSERT INTO sheriff_sales(id,property_id,state,county,
                  sheriff_number,court_case_number,plaintiff,defendant,current_sale_date,current_status,
                  judgment_amount,source_url,source_system,first_seen_at,last_seen_at,last_scraped_at,
                  raw_source_hash,is_active) VALUES(:id,:property_id,'NY',:county,:number,:case,:plaintiff,
                  :defendant,:sale_date,:status,:judgment,:url,'ny_county_official',:now,:now,:now,:hash,TRUE)"""), params)
                created += 1
        connection.execute(text("""UPDATE scrape_runs SET completed_at=NOW(),status='completed',
          records_created=:created,records_updated=:updated WHERE id=:id"""),
          {"created": created, "updated": updated, "id": run_id})
    print(f"{county}: created {created}, updated {updated}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--counties", nargs="+", choices=sorted(FILES))
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    for county in (sorted(FILES) if args.all else args.counties or []):
        load(county, FILES[county])


if __name__ == "__main__":
    main()
