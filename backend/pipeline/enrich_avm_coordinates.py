"""Enrich compact AVM rows with public NJGIN parcel centroids."""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import httpx
from sqlalchemy import text

from app.database.session import engine
from pipeline.nj_property_records import normalize_component

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "migrations" / "008_avm_parcel_coordinates.sql"
SERVICE = "https://services2.arcgis.com/XVOqAjTOJ5P6ngMu/arcgis/rest/services/Parcels_Composite_NJ_WM/FeatureServer/0/query"
SOURCE = "NJGIN Parcels and MOD-IV Composite of NJ"

def apply_migration() -> None:
    with engine.begin() as connection:
        connection.execute(text(MIGRATION.read_text()))

def wanted_keys() -> set[tuple[str, str, str, str]]:
    with engine.connect() as connection:
        rows = connection.execute(text("""
            SELECT DISTINCT municipality_code, block, lot, qualifier
            FROM nj_avm_training_sales WHERE latitude IS NULL
        """))
        return {(r[0].strip(), r[1], r[2], r[3]) for r in rows}

def fetch_centroids(client: httpx.Client, wanted) -> tuple[int, int]:
    found_total, updated_total, scanned, last_object_id = 0, 0, 0, 0
    while True:
        params={"f":"json", "where":f"PCL_MUN LIKE '13%' AND OBJECTID > {last_object_id}",
            "outFields":"OBJECTID,PCL_MUN,PCLBLOCK,PCLLOT,PCLQCODE", "returnGeometry":"false",
            "returnCentroid":"true", "outSR":4326, "resultRecordCount":2000,
            "orderByFields":"OBJECTID"}
        for attempt in range(5):
            try:
                response=client.get(SERVICE,params=params); response.raise_for_status()
                payload=response.json(); break
            except (httpx.HTTPError, ValueError):
                if attempt == 4: raise
                time.sleep(2 ** attempt)
        if "error" in payload: raise RuntimeError(payload["error"])
        features=payload.get("features",[]); page_found={}
        for feature in features:
            a, centroid = feature["attributes"], feature.get("centroid")
            last_object_id=max(last_object_id,a["OBJECTID"])
            if not centroid: continue
            key=(a["PCL_MUN"].strip(),normalize_component(a.get("PCLBLOCK") or ""),
                 normalize_component(a.get("PCLLOT") or ""),normalize_component(a.get("PCLQCODE") or ""))
            if key in wanted: page_found[key]=(centroid["y"],centroid["x"])
        if page_found:
            found_total += len(page_found); updated_total += update_rows(page_found)
        scanned += len(features)
        print(f"NJGIN parcels scanned: {scanned}; centroids found: {found_total}; rows updated: {updated_total}",flush=True)
        if not features or not payload.get("exceededTransferLimit"): break
    return found_total, updated_total

def update_rows(centroids: dict) -> int:
    statement=text("""
        UPDATE nj_avm_training_sales SET latitude=:latitude, longitude=:longitude,
            coordinate_source=:source
        WHERE municipality_code=:municipality AND block=:block AND lot=:lot
          AND qualifier=:qualifier AND latitude IS NULL
    """)
    payload=[{"municipality":k[0],"block":k[1],"lot":k[2],"qualifier":k[3],
              "latitude":v[0],"longitude":v[1],"source":SOURCE} for k,v in centroids.items()]
    updated=0
    with engine.begin() as connection:
        for start in range(0,len(payload),1000):
            result=connection.execute(statement,payload[start:start+1000]); updated += result.rowcount
    return updated

def main() -> None:
    parser=argparse.ArgumentParser(); parser.add_argument("--apply-migration",action="store_true")
    parser.add_argument("--load",action="store_true"); args=parser.parse_args()
    if not args.apply_migration and not args.load: parser.error("select an action")
    if args.apply_migration: apply_migration(); print("Migration 008 applied")
    if args.load:
        wanted=wanted_keys(); print(f"Unique parcel keys requested: {len(wanted)}")
        with httpx.Client(timeout=60) as client: found,updated=fetch_centroids(client,wanted)
        print(f"Centroids found: {found}; training rows updated: {updated}")

if __name__ == "__main__": main()
