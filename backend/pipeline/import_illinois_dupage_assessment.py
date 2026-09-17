"""Import the unrestricted DuPage County 2025 assessment parcel snapshot."""
from __future__ import annotations

import argparse
from decimal import Decimal
from typing import Any, Iterator

import httpx
from psycopg2.extras import execute_values
from sqlalchemy import text

from app.database.session import warehouse_engine
from pipeline.public_property_records import decimal_value, stable_hash, text_value

SOURCE_ID = "il_dupage_assessment_2025"
SOURCE_PAGE = "https://www.arcgis.com/home/item.html?id=267208f2ecdb44a1913ec438aadc17d4"
QUERY_URL = "https://services.arcgis.com/neJvtQ4PXvnQ86MJ/arcgis/rest/services/AssessmentParcels2025_RealEstateFile2025/FeatureServer/0/query"
FIELDS = ("OBJECTID", "PIN", "ACREAGE", "PROPADDRL1", "PROPCITY", "PROPZIP",
          "PROPCLASS", "FCVLAND", "FCVIMP", "FCVTOTAL")
COLUMNS = ("source_id", "state", "county", "source_parcel_id", "snapshot_year",
           "street_address", "city", "zip_code", "property_type", "land_use_code",
           "land_area", "land_area_unit", "land_value", "improvement_value",
           "market_value", "source_hash")
SQL = f"""INSERT INTO public_property_snapshots ({','.join(COLUMNS)}) VALUES %s
ON CONFLICT(source_id,source_parcel_id,snapshot_year) DO UPDATE SET
 street_address=EXCLUDED.street_address,city=EXCLUDED.city,zip_code=EXCLUDED.zip_code,
 property_type=EXCLUDED.property_type,land_use_code=EXCLUDED.land_use_code,
 land_area=EXCLUDED.land_area,land_area_unit=EXCLUDED.land_area_unit,
 land_value=EXCLUDED.land_value,improvement_value=EXCLUDED.improvement_value,
 market_value=EXCLUDED.market_value,source_hash=EXCLUDED.source_hash,imported_at=NOW()
WHERE public_property_snapshots.source_hash<>EXCLUDED.source_hash"""


def parcel_id(value: Any) -> str | None:
    value = text_value(value)
    return f"IL:DUPAGE:{''.join(value.upper().split())}" if value else None


def parse_snapshot(row: dict[str, Any]) -> tuple[Any, ...] | None:
    identity = parcel_id(row.get("PIN"))
    if not identity: return None
    acreage = decimal_value(row.get("ACREAGE"))
    if acreage is not None and not Decimal(0) <= acreage < Decimal("1000000000000"): acreage = None
    # FCV fields are the county's full-cash-value measures, not assessed-value fields.
    core = {"source_id": SOURCE_ID, "state": "IL", "county": "DuPage",
            "source_parcel_id": identity, "snapshot_year": 2025,
            "street_address": text_value(row.get("PROPADDRL1")),
            "city": text_value(row.get("PROPCITY")), "zip_code": text_value(row.get("PROPZIP")),
            "property_type": text_value(row.get("PROPCLASS")), "land_use_code": text_value(row.get("PROPCLASS")),
            "land_area": acreage, "land_area_unit": "acres",
            "land_value": decimal_value(row.get("FCVLAND")),
            "improvement_value": decimal_value(row.get("FCVIMP")),
            "market_value": decimal_value(row.get("FCVTOTAL"))}
    return tuple(core[name] for name in COLUMNS[:-1]) + (stable_hash(core),)


def pages(client: httpx.Client, page_size: int) -> Iterator[list[dict[str, Any]]]:
    after = 0
    while True:
        response = client.get(QUERY_URL, params={"where": f"OBJECTID>{after}", "outFields": ",".join(FIELDS),
                              "returnGeometry": "false", "orderByFields": "OBJECTID", "resultRecordCount": page_size,
                              "f": "json"})
        response.raise_for_status(); payload = response.json()
        if payload.get("error"): raise RuntimeError(payload["error"])
        rows = [feature["attributes"] for feature in payload.get("features", [])]
        if not rows: break
        yield rows; after = rows[-1]["OBJECTID"]
        if len(rows) < page_size: break


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--page-size", type=int, default=2000)
    parser.add_argument("--batch-size", type=int, default=10000); args = parser.parse_args()
    with warehouse_engine.begin() as connection:
        connection.execute(text("""INSERT INTO public_data_sources(source_id,state,county,source_name,source_url,access_method,coverage_notes,last_checked_at)
          VALUES(:id,'IL','DuPage','DuPage County 2025 Final Assessment Parcels',:url,'ArcGIS FeatureServer',
          'Final 2025 parcel, situs, class, acreage, and full-cash values; billing and ownership fields excluded',NOW())
          ON CONFLICT(source_id) DO UPDATE SET last_checked_at=NOW(),updated_at=NOW()"""), {"id": SOURCE_ID, "url": SOURCE_PAGE})
    raw = warehouse_engine.raw_connection(); loaded = 0; batch: dict[str, tuple[Any, ...]] = {}
    try:
        cursor = raw.cursor()
        with httpx.Client(timeout=180, follow_redirects=True) as client:
            for page in pages(client, args.page_size):
                for row in page:
                    parsed = parse_snapshot(row)
                    if parsed: batch[parsed[3]] = parsed
                if len(batch) >= args.batch_size:
                    execute_values(cursor, SQL, list(batch.values()), page_size=args.batch_size); loaded += len(batch); batch.clear(); raw.commit()
                    print(f"DuPage 2025: {loaded:,}", flush=True)
        if batch: execute_values(cursor, SQL, list(batch.values()), page_size=args.batch_size); loaded += len(batch); raw.commit()
    finally: raw.close()
    print(f"complete DuPage 2025 snapshots={loaded:,}")


if __name__ == "__main__": main()
