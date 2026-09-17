"""Import unrestricted Lake County parcel points without taxpayer fields."""
from __future__ import annotations

import argparse
from typing import Any, Iterator

import httpx
from psycopg2.extras import execute_values
from sqlalchemy import text

from app.database.session import warehouse_engine
from pipeline.public_property_records import decimal_value, stable_hash, text_value

SOURCE_ID = "il_lake_open_parcels_2026"
SOURCE_PAGE = "https://hub.arcgis.com/datasets/lakecountyil::tax-parcels"
QUERY_URL = "https://services3.arcgis.com/HESxeTbDliKKvec2/arcgis/rest/services/OpenData_ParcelPolygons/FeatureServer/1/query"
FIELDS = ("OBJECTID", "PIN", "situs_addr", "situs_ad_1", "situs_ad_3", "situs_ad_5")
COLUMNS = ("source_id", "state", "county", "source_parcel_id", "snapshot_year",
           "street_address", "city", "zip_code", "longitude", "latitude", "source_hash")
SQL = f"""INSERT INTO public_property_snapshots ({','.join(COLUMNS)}) VALUES %s
ON CONFLICT(source_id,source_parcel_id,snapshot_year) DO UPDATE SET
 street_address=EXCLUDED.street_address,city=EXCLUDED.city,zip_code=EXCLUDED.zip_code,
 longitude=EXCLUDED.longitude,latitude=EXCLUDED.latitude,source_hash=EXCLUDED.source_hash,
 imported_at=NOW() WHERE public_property_snapshots.source_hash<>EXCLUDED.source_hash"""


def parcel_id(value: Any) -> str | None:
    value = text_value(value)
    return f"IL:LAKE:{''.join(character for character in value.upper() if character.isalnum())}" if value else None


def parse_feature(feature: dict[str, Any]) -> tuple[Any, ...] | None:
    row, geometry = feature.get("attributes", {}), feature.get("geometry", {})
    identity = parcel_id(row.get("PIN"))
    if not identity: return None
    core = {"source_id": SOURCE_ID, "state": "IL", "county": "Lake", "source_parcel_id": identity,
            "snapshot_year": 2026, "street_address": text_value(row.get("situs_ad_1")),
            "city": text_value(row.get("situs_addr")), "zip_code": text_value(row.get("situs_ad_5")),
            "longitude": decimal_value(geometry.get("x")), "latitude": decimal_value(geometry.get("y"))}
    return tuple(core[name] for name in COLUMNS[:-1]) + (stable_hash(core),)


def pages(client: httpx.Client, page_size: int) -> Iterator[list[dict[str, Any]]]:
    after = 0
    while True:
        response = client.get(QUERY_URL, params={"where": f"OBJECTID>{after}", "outFields": ",".join(FIELDS),
            "returnGeometry": "true", "outSR": 4326, "orderByFields": "OBJECTID",
            "resultRecordCount": page_size, "f": "json"})
        response.raise_for_status(); payload = response.json()
        if payload.get("error"): raise RuntimeError(payload["error"])
        features = payload.get("features", [])
        if not features: break
        yield features; after = features[-1]["attributes"]["OBJECTID"]
        if len(features) < page_size: break


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--page-size", type=int, default=2000)
    parser.add_argument("--batch-size", type=int, default=10000); args = parser.parse_args()
    with warehouse_engine.begin() as connection:
        connection.execute(text("""INSERT INTO public_data_sources(source_id,state,county,source_name,source_url,access_method,coverage_notes,last_checked_at)
          VALUES(:id,'IL','Lake','Lake County Tax Parcel Points',:url,'ArcGIS FeatureServer',
          'Weekly parcel PIN, situs address and point coordinates; taxpayer fields excluded; County license permits free business use',NOW())
          ON CONFLICT(source_id) DO UPDATE SET last_checked_at=NOW(),updated_at=NOW()"""), {"id": SOURCE_ID, "url": SOURCE_PAGE})
    raw = warehouse_engine.raw_connection(); loaded = 0; batch: dict[str, tuple[Any, ...]] = {}
    try:
        cursor = raw.cursor()
        with httpx.Client(timeout=180, follow_redirects=True) as client:
            for page in pages(client, args.page_size):
                for feature in page:
                    parsed = parse_feature(feature)
                    if parsed: batch[parsed[3]] = parsed
                if len(batch) >= args.batch_size:
                    execute_values(cursor, SQL, list(batch.values()), page_size=args.batch_size)
                    loaded += len(batch); batch.clear(); raw.commit(); print(f"Lake parcels: {loaded:,}", flush=True)
        if batch: execute_values(cursor, SQL, list(batch.values()), page_size=args.batch_size); loaded += len(batch); raw.commit()
    finally: raw.close()
    print(f"complete Lake parcel snapshots={loaded:,}")


if __name__ == "__main__": main()
