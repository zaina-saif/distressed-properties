"""Find recorded documents for Hillsborough auction cases (metadata only).

The official-records index is not the HOVER court docket. Its matches are
candidate documents, not verified judgment amounts.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import httpx

from pipeline.scrape_hillsborough_foreclosure_notices import OUTPUT as NOTICES

API = "https://publicaccess.hillsclerk.com/PAVDirectSearch/api/CustomQuery/KeywordSearch"
OUTPUT = Path("data/sheriff_sales/hillsborough_official_record_candidates.json")


def search_case(client: httpx.Client, case_number: str) -> list[dict]:
    response = client.post(API, json={"QueryID": 350,
                                      "Keywords": [{"ID": 1259, "Value": case_number}],
                                      "QueryLimit": 300})
    response.raise_for_status()
    payload = response.json()
    if payload.get("Truncated"):
        raise ValueError(f"Official-records results truncated for {case_number}")
    columns = [column["Heading"] for column in payload.get("DisplayColumns") or []]
    results = []
    for document in payload.get("Data", []):
        values = document.get("DisplayColumnValues") or []
        fields = {heading: values[index].get("Value") for index, heading in enumerate(columns)
                  if index < len(values)}
        results.append({"document_id": document.get("ID"),
                        "display_name": document.get("Name"),
                        "fields": fields})
    return results


def inspect(input_path: Path = NOTICES, delay: float = 0.4) -> dict:
    notices = json.loads(input_path.read_text())["records"]
    cases = sorted({record["court_case_number"] for record in notices})
    results = []
    with httpx.Client(timeout=30, follow_redirects=True,
                      headers={"User-Agent": "nj-sheriff-sale-platform/1.0 (public records research)"}) as client:
        for case_number in cases:
            results.append({"case_number": case_number,
                            "documents": search_case(client, case_number)})
            time.sleep(delay)
    return {"source_url": API, "records": results}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=NOTICES)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--delay", type=float, default=0.4)
    args = parser.parse_args()
    result = inspect(args.input, args.delay)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"cases": len(result["records"]),
                      "cases_with_documents": sum(bool(item["documents"]) for item in result["records"]),
                      "documents": sum(len(item["documents"]) for item in result["records"]),
                      "output": str(args.output)}))


if __name__ == "__main__":
    main()
