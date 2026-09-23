"""Apply reviewed facts from locally supplied Kings County foreclosure PDFs."""
from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from pypdf import PdfReader
from sqlalchemy import text

from app.database.session import engine
from pipeline.load_nyc_kings_court_foreclosures import DEFAULT_INPUT as INDEX_INPUT
from pipeline.load_nyc_kings_court_foreclosures import SOURCE_SYSTEM

DETAILS_INPUT = Path("data/sheriff_sales/nyc_kings_court_notice_details.json")
PDF_DIR = Path("../.local/nyc-kings-court-pdfs")


def validate(records: list[dict], pdf_dir: Path = PDF_DIR) -> None:
    index = json.loads(INDEX_INPUT.read_text())
    expected = set(index["notice_filenames"])
    seen = set()
    for record in records:
        filename = record["filename"]
        if filename in seen or filename not in expected:
            raise ValueError(f"Duplicate or unindexed PDF: {filename}")
        seen.add(filename)
        if record["sale_date"] != index["sale_date"] or record["sale_result"] is not None:
            raise ValueError(f"Unverified sale date or outcome: {filename}")
        if record["bbl"] != "3" + record["block"].zfill(5) + record["lot"].zfill(4):
            raise ValueError(f"BBL/block/lot mismatch: {filename}")
        if not record["court_case_number"] or not record["address"].endswith(
            f"Brooklyn, NY {record['zip_code']}"
        ):
            raise ValueError(f"Missing case or address identity: {filename}")
        if record["judgment_amount"] is not None and record["lien_amount"] is not None:
            raise ValueError(f"Judgment and lien amounts conflated: {filename}")
        pdf_path = pdf_dir / filename
        if not pdf_path.is_file() or not pdf_path.read_bytes().startswith(b"%PDF-"):
            raise ValueError(f"Missing valid local PDF: {filename}")
        if not PdfReader(str(pdf_path)).pages:
            raise ValueError(f"Empty local PDF: {filename}")


def load(path: Path = DETAILS_INPUT, pdf_dir: Path = PDF_DIR) -> dict[str, int]:
    records = json.loads(path.read_text())
    validate(records, pdf_dir)
    index = json.loads(INDEX_INPUT.read_text())
    run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    updated = 0
    with engine.begin() as connection:
        connection.execute(text("""INSERT INTO scrape_runs
            (id,job_name,county,source_system,started_at,status,records_found)
            VALUES(:id,'nyc_kings_local_pdf_enrichment','Kings',:source,:now,'running',:count)"""),
            {"id": run_id, "source": SOURCE_SYSTEM, "now": now, "count": len(records)})
        for record in records:
            filename = record["filename"]
            pdf_data = (pdf_dir / filename).read_bytes()
            pdf_hash = hashlib.sha256(pdf_data).hexdigest()
            number = ("KINGS-" + record["sale_date"].replace("-", "") + "-"
                      + hashlib.sha256(filename.encode()).hexdigest()[:12])
            source_url = index["source_directory_url"] + quote(filename)
            sale = connection.execute(text("""SELECT id,property_id FROM sheriff_sales
                WHERE source_system=:source AND sheriff_number=:number
                  AND county='Kings' AND state='NY' FOR UPDATE"""),
                {"source": SOURCE_SYSTEM, "number": number}).mappings().first()
            if sale is None:
                raise ValueError(f"Provisional court listing not found: {filename}")
            connection.execute(text("""UPDATE properties SET
                normalized_address=:address,street_address=:street,
                unit_number=:unit,zip_code=:zip,block=:block,lot=:lot,
                property_type=COALESCE(:property_type,property_type),
                data_quality_score=85,updated_at=NOW() WHERE id=:id"""),
                {"id": sale["property_id"], "address": record["address"],
                 "street": record["street_address"],
                 "unit": record.get("unit_number"), "zip": record["zip_code"],
                 "block": record["block"], "lot": record["lot"],
                 "property_type": record["property_type"]})
            details = (f"Official Kings County foreclosure notice; BBL {record['bbl']}; "
                       f"Referee: {record['referee'].rstrip('.')}. "
                       f"Plaintiff attorney: {record['plaintiff_attorney']}. "
                       f"Notice completeness: {record['notice_completeness']}.")
            if record["lien_amount"] is not None:
                details += (f" Approximate lien amount: ${record['lien_amount']:,.2f}; "
                            "the notice does not call this a judgment amount.")
            details += " Auction outcome not verified."
            connection.execute(text("""UPDATE sheriff_sales SET
                court_case_number=:case_number,property_number=:bbl,
                plaintiff=:plaintiff,defendant=:defendant,
                plaintiff_attorney=:attorney,
                judgment_amount=COALESCE(:judgment_amount,judgment_amount),
                notice_lien_amount=:lien_amount,
                description_text=:details,source_url=:source_url,
                raw_source_hash=:pdf_hash,last_scraped_at=:now,
                updated_at=NOW() WHERE id=:id"""),
                {"id": sale["id"], "case_number": record["court_case_number"],
                 "bbl": record["bbl"], "plaintiff": record["plaintiff"],
                 "defendant": record["defendant"], "attorney": record["plaintiff_attorney"],
                 "judgment_amount": record["judgment_amount"],
                 "lien_amount": record["lien_amount"], "details": details,
                 "source_url": source_url, "pdf_hash": pdf_hash, "now": now})
            payload = {**record, "pdf_sha256": pdf_hash, "extraction_method": "macos_vision_ocr"}
            payload_json = json.dumps(payload, sort_keys=True)
            connection.execute(text("""INSERT INTO raw_scrape_records
                (id,scrape_run_id,state,county,source_record_id,source_url,raw_payload,
                 content_hash,parsing_status,scraped_at)
                VALUES(:id,:run,'NY','Kings',:number,:url,CAST(:payload AS JSONB),
                       :hash,'parsed',:now) ON CONFLICT DO NOTHING"""),
                {"id": str(uuid.uuid4()), "run": run_id, "number": number,
                 "url": source_url, "payload": payload_json,
                 "hash": hashlib.sha256(payload_json.encode()).hexdigest(), "now": now})
            updated += 1
        connection.execute(text("""UPDATE scrape_runs SET completed_at=NOW(),status='completed',
            records_updated=:updated WHERE id=:id"""),
            {"updated": updated, "id": run_id})
    return {"updated": updated, "remaining_index_only": len(index["notice_filenames"]) - updated}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DETAILS_INPUT)
    parser.add_argument("--pdf-dir", type=Path, default=PDF_DIR)
    args = parser.parse_args()
    print(json.dumps(load(args.input, args.pdf_dir)))


if __name__ == "__main__":
    main()
