"""Scrape Ocean County's official current sheriff-sale PDF."""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import httpx
from pypdf import PdfReader

from pipeline.load_to_supabase import load_into_supabase


PDF_URL = "https://co.ocean.nj.us/WebContentFiles/3ec14ac4-25a1-41cd-8c8b-d9996a9d686c.pdf"
DEFAULT_OUTPUT = Path("data/sheriff_sales/ocean_all_sheriff_sales.json")


def _date(value: str) -> str:
    return datetime.strptime(value, "%m/%d/%Y").isoformat()


def _field(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text, re.MULTILINE)
    return match.group(1).strip() if match else None


def parse_pdf(pdf_content: bytes) -> list[dict]:
    reader = PdfReader(BytesIO(pdf_content))
    records: list[dict] = []

    for page in reader.pages:
        page_text = page.extract_text(extraction_mode="layout") or ""
        header_date = _field(r"REAL ESTATE LISTING FOR\s+(\d{2}/\d{2}/\d{4})", page_text)
        if not header_date:
            continue

        chunks = re.split(r"(?=^\s*CH\s+\d+\s*$)", page_text, flags=re.MULTILINE)
        for chunk in chunks:
            case_id = _field(r"^\s*CH\s+(\d+)\s*$", chunk)
            if not case_id:
                continue

            docket_match = re.search(r"^\s*(F[0-9-]+)\s+DEFENDANT\s+(.+?)\s*$", chunk, re.MULTILINE)
            plaintiff_match = re.search(
                r"PLAINTIFF\s+(.+?)\s{2,}\$([\d,]+\.\d{2})", chunk, re.MULTILINE
            )
            address_match = re.search(
                r"SEQ\s+\d+\s+(.+?)\s{2,}([A-Z][A-Z .-]+?)\s+NJ\s+(\d{5})\s*$",
                chunk,
                re.MULTILINE,
            )
            if not docket_match or not plaintiff_match or not address_match:
                raise ValueError(f"Unable to parse Ocean County record CH {case_id}")

            street, municipality, zip_code = (value.strip() for value in address_match.groups())
            raw_status = "Scheduled"
            status = "scheduled"
            sale_date = header_date
            adjourned = _field(
                r"ADJOURNED UNTIL[\s\S]{0,200}?(\d{2}/\d{2}/\d{4})", chunk
            )
            if adjourned:
                raw_status = f"Adjourned until {adjourned}"
                sale_date = adjourned
            elif re.search(r"\bCANCELLATION\b", chunk):
                raw_status = "Cancellation"
                status = "cancelled"
            elif re.search(r"\bBANKRUPTCY\b", chunk):
                raw_status = "Bankruptcy"
                status = "bankruptcy"

            upset_price = Decimal(plaintiff_match.group(2).replace(",", ""))
            docket_number = docket_match.group(1)
            defendant = docket_match.group(2).strip()
            plaintiff = plaintiff_match.group(1).strip()
            address = f"{street} {municipality} NJ {zip_code}"
            lot = _field(r"Lot:\s*(.+?)\s{2,}Block:", chunk)
            block = _field(r"Block:\s*(.+?)\s*$", chunk)
            source_url = PDF_URL

            records.append(
                {
                    "sheriff_number": f"CH-{case_id}",
                    "state": "NJ",
                    "county": "Ocean",
                    "status": status,
                    "sale_date": _date(sale_date),
                    "address": address,
                    "judgment_amount": None,
                    "upset_price": str(upset_price),
                    "source_url": source_url,
                    "raw_payload": {
                        "plaintiff": plaintiff,
                        "defendant": defendant,
                        "raw_status": raw_status,
                        "description_text": chunk.strip(),
                        "description_source_url": source_url,
                        "status_history": [
                            {
                                "status": status,
                                "raw_status": raw_status,
                                "sale_date": _date(sale_date),
                            }
                        ],
                        "parsed_description": {
                            "docket_number": docket_number,
                            "block": block,
                            "lot": lot,
                            "parser_version": "ocean-pdf-v1",
                        },
                    },
                }
            )

    return records


def scrape(output: Path = DEFAULT_OUTPUT) -> Path:
    response = httpx.get(PDF_URL, follow_redirects=True, timeout=60)
    response.raise_for_status()
    records = parse_pdf(response.content)
    if not records:
        raise RuntimeError("Ocean County PDF contained no parseable sheriff-sale records")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    print(f"Ocean: {len(records)} records saved to {output}")
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--load", action="store_true")
    args = parser.parse_args()
    output = scrape(args.output)
    if args.load:
        load_into_supabase(output)


if __name__ == "__main__":
    main()
