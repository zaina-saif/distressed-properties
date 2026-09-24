"""Persist Apify Zillow datasets and their address-level audit trail."""
from __future__ import annotations

import argparse
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

from app.database.session import engine

ACTOR = "maxcopell~zillow-detail-scraper"


def parse_time(value: str | None, fallback: datetime) -> datetime:
    if not value:
        return fallback
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def persist(output_dir: Path) -> dict[str, int]:
    manifest = json.loads((output_dir / "manifest.json").read_text())
    dataset = json.loads((output_dir / "dataset.json").read_text())
    run = json.loads((output_dir / "run.json").read_text())
    submission = json.loads((output_dir / "submission.json").read_text())
    metadata_path = output_dir / "dataset-metadata.json"
    metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
    retrieved_at = parse_time(run.get("finishedAt") or run.get("stoppedAt"), datetime.now(timezone.utc))
    submitted_at = parse_time(submission.get("submitted_at"), retrieved_at)
    by_address = {
        str(item.get("addressOrUrlFromInput", "")).strip(): item
        for item in dataset
        if str(item.get("addressOrUrlFromInput", "")).strip()
    }
    matched = no_match = 0
    with engine.begin() as connection:
        db_run_id = connection.execute(text("""INSERT INTO apify_zillow_runs
            (apify_run_id,actor,dataset_id,submitted_at,retrieved_at,status,
             submitted_address_count,returned_item_count,metadata)
            VALUES(:run_id,:actor,:dataset_id,:submitted_at,:retrieved_at,:status,
                   :submitted_count,:returned_count,CAST(:metadata AS JSONB))
            ON CONFLICT(apify_run_id) DO UPDATE SET dataset_id=EXCLUDED.dataset_id,
                retrieved_at=EXCLUDED.retrieved_at,status=EXCLUDED.status,
                submitted_address_count=EXCLUDED.submitted_address_count,
                returned_item_count=EXCLUDED.returned_item_count,metadata=EXCLUDED.metadata
            RETURNING id"""), {
                "run_id": run["id"], "actor": ACTOR,
                "dataset_id": run.get("defaultDatasetId"), "submitted_at": submitted_at,
                "retrieved_at": retrieved_at, "status": run.get("status", "SUCCEEDED"),
                "submitted_count": len(manifest), "returned_count": len(dataset),
                "metadata": json.dumps(metadata),
            }).scalar_one()
        connection.execute(text("""UPDATE apify_zillow_results SET is_current=FALSE
            WHERE run_id=:run_id OR property_id IN (
                SELECT property_id FROM apify_zillow_results WHERE run_id=:run_id
                  AND property_id IS NOT NULL)"""), {"run_id": db_run_id})
        for row in manifest:
            address = row["input_address"].strip()
            item = by_address.get(address)
            status = "matched" if item else "no_match"
            if item:
                matched += 1
            else:
                no_match += 1
            zestimate = item.get("zestimate") if item else None
            payload = json.dumps(item or {})
            connection.execute(text("""INSERT INTO apify_zillow_results
                (run_id,property_id,submitted_address,match_status,zillow_id,zestimate,
                 raw_payload,retrieved_at,is_current)
                VALUES(:run_id,:property_id,:address,:status,:zpid,:zestimate,
                       CAST(:payload AS JSONB),:retrieved_at,TRUE)
                ON CONFLICT(run_id,submitted_address) DO UPDATE SET
                    property_id=EXCLUDED.property_id,match_status=EXCLUDED.match_status,
                    zillow_id=EXCLUDED.zillow_id,zestimate=EXCLUDED.zestimate,
                    raw_payload=EXCLUDED.raw_payload,retrieved_at=EXCLUDED.retrieved_at,
                    is_current=TRUE"""), {
                    "run_id": db_run_id, "property_id": row["property_id"],
                    "address": address, "status": status,
                    "zpid": str(item["zpid"]) if item and item.get("zpid") is not None else None,
                    "zestimate": zestimate, "payload": payload, "retrieved_at": retrieved_at,
                })
            if item and zestimate is not None:
                connection.execute(text("""UPDATE property_valuations SET is_current=FALSE
                    WHERE property_id=:property_id AND provider='zillow_apify' AND is_current=TRUE"""),
                    {"property_id": row["property_id"]})
                connection.execute(text("""INSERT INTO property_valuations
                    (property_id,provider,estimated_value,provider_property_id,provider_response,
                     effective_date,retrieved_at,is_current)
                    VALUES(:property_id,'zillow_apify',:zestimate,:zpid,CAST(:payload AS JSONB),
                           :effective_date,:retrieved_at,TRUE)"""), {
                    "property_id": row["property_id"], "zestimate": zestimate,
                    "zpid": str(item["zpid"]) if item.get("zpid") is not None else None,
                    "payload": payload, "effective_date": retrieved_at.date(),
                    "retrieved_at": retrieved_at,
                })
    return {"run_id": run["id"], "submitted": len(manifest), "returned": len(dataset),
            "matched": matched, "no_match": no_match}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", nargs="+", type=Path)
    args = parser.parse_args()
    for path in args.output_dir:
        print(json.dumps(persist(path)))


if __name__ == "__main__":
    main()
