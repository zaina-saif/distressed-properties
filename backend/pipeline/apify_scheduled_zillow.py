"""One-batch scheduled-property enrichment; checkpoint before submitting paid work."""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import time

import httpx
from sqlalchemy import text
from dotenv import load_dotenv

from app.database.session import engine

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = Path(os.environ.get("APIFY_OUTPUT_DIR", ROOT / ".local/apify-zillow-scheduled"))
ACTOR = "maxcopell~zillow-detail-scraper"
API = "https://api.apify.com/v2"
TARGET_STATE = os.environ.get("APIFY_STATE")
EXPECTED_COUNT = os.environ.get("APIFY_EXPECTED_COUNT")

load_dotenv(ROOT / "backend/.env")


def save(name, value):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / name
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, default=str) + "\n")
    temp.replace(path)


def prepare():
    if (OUTPUT / "submission.json").exists():
        raise RuntimeError("A submission already exists. Resume it; do not replace its manifest.")
    with engine.connect() as connection:
        rows = connection.execute(text("""
            SELECT p.id::text AS property_id, ss.id::text AS sheriff_sale_id,
                   p.normalized_address, p.street_address, p.city, p.state, p.zip_code,
                   ss.current_status, ss.current_sale_date
            FROM sheriff_sales ss JOIN properties p ON p.id=ss.property_id
            WHERE (:state IS NULL OR p.state=:state)
              AND strpos(LOWER(CASE
                WHEN ss.source_system IN ('nyc_kings_court_foreclosure_index',
                    'fl_hillsborough_published_foreclosure_notice')
                    AND ss.current_sale_date<CURRENT_DATE
                    AND ss.current_status='scheduled_unverified'
                THEN 'date_passed_unverified' ELSE ss.current_status END), 'scheduled') > 0
            ORDER BY p.normalized_address, ss.id
        """), {"state": TARGET_STATE}).mappings().all()
    manifest = [dict(row) for row in rows]
    for row in manifest:
        row["input_address"] = row["normalized_address"].strip()
    if any(not row["input_address"] for row in manifest):
        raise RuntimeError("Blank input address; review manifest before submitting.")
    save("manifest.json", manifest)
    save("input.json", {"addresses": [row["input_address"] for row in manifest]})
    print(json.dumps({"rows": len(manifest), "distinct_properties": len({r['property_id'] for r in manifest}),
                      "distinct_addresses": len({r['input_address'] for r in manifest}),
                      "statuses": sorted({r['current_status'] for r in manifest})}), flush=True)


def client():
    token = os.environ.get("APIFY_API_TOKEN")
    if not token:
        raise RuntimeError("APIFY_API_TOKEN is missing")
    return httpx.Client(base_url=API, headers={"Authorization": f"Bearer {token}"}, timeout=120)


def get(client, path, **kwargs):
    for attempt in range(4):
        try:
            response = client.get(path, **kwargs)
            response.raise_for_status()
            return response.json()
        except (httpx.TransportError, httpx.HTTPStatusError):
            if attempt == 3:
                raise
            time.sleep(15)


def submit():
    marker = OUTPUT / "submission.json"
    if marker.exists():
        raise RuntimeError("Submission marker exists; use watch, never submit twice.")
    payload = json.loads((OUTPUT / "input.json").read_text())
    if EXPECTED_COUNT and len(payload["addresses"]) != int(EXPECTED_COUNT):
        raise RuntimeError(f"Expected {EXPECTED_COUNT} addresses; found {len(payload['addresses'])}. Review before submitting.")
    with client() as api:
        # Exclusive creation protects against concurrent/double submission. No POST retries.
        with marker.open("x") as handle:
            json.dump({"submitted_at": datetime.now(timezone.utc).isoformat(),
                       "actor": ACTOR, "count": len(payload["addresses"]),
                       "status": "SUBMITTING"}, handle)
        response = api.post(f"/acts/{ACTOR}/runs", json=payload)
        response.raise_for_status()
        run = response.json()["data"]
        save("run.json", run)
        save("submission.json", {"run_id": run["id"], "actor": ACTOR,
                                 "count": len(payload["addresses"]), "status": run["status"]})
        print(json.dumps({"run_id": run["id"], "status": run["status"]}), flush=True)


def watch():
    run = json.loads((OUTPUT / "run.json").read_text())
    with client() as api:
        while True:
            run = get(api, f"/actor-runs/{run['id']}")["data"]
            save("run.json", run)
            print(f"{datetime.now(timezone.utc).isoformat()} {run['id']} {run['status']}", flush=True)
            if run["status"] == "SUCCEEDED":
                break
            if run["status"] in {"FAILED", "ABORTED", "TIMED-OUT"}:
                raise RuntimeError(f"Run ended with {run['status']}; no new run was submitted.")
            time.sleep(15)
        dataset = run["defaultDatasetId"]
        metadata = get(api, f"/datasets/{dataset}")["data"]
        save("dataset-metadata.json", metadata)
        items = []
        while True:
            batch = get(api, f"/datasets/{dataset}/items", params={
                "format": "json", "offset": len(items), "limit": 1000,
            })
            if not batch:
                break
            items.extend(batch)
        save("dataset.json", items)
        if len(items) != metadata["itemCount"]:
            # Apify's metadata can lag briefly while an actor finalizes its
            # dataset. The downloaded endpoint is authoritative here; retain
            # the discrepancy for auditability without discarding valid items.
            metadata["downloadedItemCount"] = len(items)
            save("dataset-metadata.json", metadata)
            print(f"Dataset metadata reported {metadata['itemCount']}; downloaded {len(items)} items.", flush=True)
        print(f"Saved all {len(items)} items to {OUTPUT / 'dataset.json'}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "submit", "watch"])
    args = parser.parse_args()
    {"prepare": prepare, "submit": submit, "watch": watch}[args.action]()
