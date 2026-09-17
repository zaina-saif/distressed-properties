"""Import the official Warren County, Ohio sheriff-sale table."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import text

from app.database.session import engine
from pipeline.import_ohio_henry_sales import money


SOURCE_URL = "https://sheriff.warrencountyohio.gov/SheriffSales/SLSGrid/Index"
OUTPUT = Path("data/sheriff_sales/oh_warren_sheriff_sales.json")


def normalize_status(raw: str) -> str:
    value = raw.strip().lower()
    if "cancel" in value or "vacat" in value:
        return "cancelled"
    if "resched" in value or "postpon" in value or "stay" in value:
        return "postponed"
    if "sold" in value:
        return "sold"
    if "schedule" in value or "active" in value:
        return "scheduled"
    return "unknown"


def parse_html(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    records = []
    for row in soup.select("#slsgrid tbody tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) != 11:
            continue
        details = cells[0].find("input")
        onclick = details.get("onclick", "") if details else ""
        source_id = re.search(r"LoadDetails\('([^']+)'", onclick)
        values = [" ".join(cell.stripped_strings) for cell in cells]
        case = re.sub(r"^(?:Alias\s+)+", "", values[3], flags=re.I).strip()
        date_match = re.search(r"\d{2}/\d{2}/\d{4}", values[9])
        address = re.sub(r"\s+,", ",", values[8]).strip()
        raw_status = values[10].strip()
        sheriff_number = f"WARREN-{source_id.group(1) if source_id else case}"
        records.append({
            "state": "OH", "county": "Warren", "sheriff_number": sheriff_number,
            "court_case_number": case, "address": address,
            "sale_date": datetime.strptime(date_match.group(), "%m/%d/%Y").date().isoformat() if date_match else None,
            "status": normalize_status(raw_status), "upset_price": money(values[6]),
            "judgment_amount": money(values[5]), "source_url": SOURCE_URL,
            "plaintiff": values[1] or None, "defendant": values[2] or None,
            "raw_payload": {"source_record_id": source_id.group(1) if source_id else None,
                            "parcel_number": values[7], "appraised_value": money(values[4]),
                            "starting_bid": money(values[6]), "sale_date_note": values[9],
                            "raw_status": raw_status},
        })
    return records


def fetch() -> list[dict]:
    response = httpx.get(SOURCE_URL, follow_redirects=True, timeout=45)
    response.raise_for_status()
    return parse_html(response.text)


def write_output(records: list[dict], output: Path = OUTPUT) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(records, indent=2, sort_keys=True) + "\n")


def load(records: list[dict]) -> tuple[int, int]:
    run_id, now = str(uuid.uuid4()), datetime.now(timezone.utc)
    created = updated = 0
    with engine.begin() as connection:
        connection.execute(text("""INSERT INTO scrape_runs(id,job_name,county,source_system,started_at,status,records_found)
          VALUES(:id,'oh_warren_official_listing','Warren','oh_county_official',:now,'running',:count)"""),
          {"id": run_id, "now": now, "count": len(records)})
        for record in records:
            normalized = " ".join(record["address"].split())
            match = re.search(r"^(.*)\s+([A-Za-z .'-]+),\s*OH\s+(\d{5})$", normalized)
            street, city, zip_code = (match.group(1), match.group(2).strip(), match.group(3)) if match else (normalized, "Unknown", None)
            address_hash = hashlib.sha256(f"OH|WARREN|{normalized.upper()}".encode()).hexdigest()
            property_id = connection.execute(text("""INSERT INTO properties(id,normalized_address,street_address,city,municipality,county,state,zip_code,address_hash,data_quality_score)
              VALUES(:id,:address,:street,:city,:city,'Warren','OH',:zip,:hash,75)
              ON CONFLICT(address_hash) DO UPDATE SET updated_at=NOW() RETURNING id"""),
              {"id": str(uuid.uuid4()), "address": normalized, "street": street, "city": city, "zip": zip_code, "hash": address_hash}).scalar_one()
            content_hash = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
            existing = connection.execute(text("SELECT id FROM sheriff_sales WHERE state='OH' AND county='Warren' AND sheriff_number=:number"), {"number": record["sheriff_number"]}).scalar()
            params = {"id": existing or str(uuid.uuid4()), "property_id": property_id, "number": record["sheriff_number"],
                      "case": record["court_case_number"], "plaintiff": record["plaintiff"], "defendant": record["defendant"],
                      "sale_date": record["sale_date"], "status": record["status"], "upset": record["upset_price"],
                      "judgment": record["judgment_amount"], "url": record["source_url"], "now": now, "hash": content_hash,
                      "property_number": record["raw_payload"]["source_record_id"], "map": record["raw_payload"]["parcel_number"],
                      "result": record["raw_payload"]["raw_status"], "active": record["status"] == "scheduled"}
            if existing:
                connection.execute(text("""UPDATE sheriff_sales SET property_id=:property_id,court_case_number=:case,plaintiff=:plaintiff,defendant=:defendant,current_sale_date=:sale_date,current_status=:status,upset_price=:upset,judgment_amount=:judgment,source_url=:url,last_seen_at=:now,last_scraped_at=:now,raw_source_hash=:hash,property_number=:property_number,map_number=:map,sale_result=:result,is_active=:active,updated_at=NOW() WHERE id=:id"""), params)
                updated += 1
            else:
                connection.execute(text("""INSERT INTO sheriff_sales(id,property_id,state,county,sheriff_number,court_case_number,plaintiff,defendant,current_sale_date,current_status,upset_price,judgment_amount,source_url,source_system,first_seen_at,last_seen_at,last_scraped_at,raw_source_hash,is_active,property_number,map_number,sale_result) VALUES(:id,:property_id,'OH','Warren',:number,:case,:plaintiff,:defendant,:sale_date,:status,:upset,:judgment,:url,'oh_county_official',:now,:now,:now,:hash,:active,:property_number,:map,:result)"""), params)
                created += 1
            connection.execute(text("""INSERT INTO raw_scrape_records(id,scrape_run_id,state,county,source_record_id,source_url,raw_payload,content_hash,parsing_status,scraped_at) VALUES(:id,:run,'OH','Warren',:number,:url,CAST(:payload AS JSONB),:hash,'parsed',:now) ON CONFLICT DO NOTHING"""),
              {"id": str(uuid.uuid4()), "run": run_id, "number": record["sheriff_number"], "url": record["source_url"], "payload": json.dumps(record), "hash": content_hash, "now": now})
        connection.execute(text("UPDATE scrape_runs SET completed_at=NOW(),status='completed',records_created=:created,records_updated=:updated WHERE id=:id"), {"created": created, "updated": updated, "id": run_id})
    return created, updated


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", type=Path, help="Parse a saved official page instead of fetching it")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--load", action="store_true")
    args = parser.parse_args()
    records = parse_html(args.html.read_text()) if args.html else fetch()
    write_output(records, args.output)
    print(f"parsed {len(records)} Warren County sheriff sales")
    if args.load:
        created, updated = load(records)
        print(f"created {created}, updated {updated}")


if __name__ == "__main__":
    main()
