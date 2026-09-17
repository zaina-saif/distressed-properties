"""Import non-personal fields from Madison County's official parcel layer."""
from __future__ import annotations

import argparse
from decimal import Decimal
from typing import Any, Iterator

import httpx
from psycopg2.extras import execute_values
from sqlalchemy import text

from app.database.session import warehouse_engine
from pipeline.public_property_records import decimal_value, stable_hash, text_value

SOURCE_ID = "il_madison_open_parcels_2026"
SOURCE_PAGE = "https://gis-data-madcoil.hub.arcgis.com/"
QUERY_URL = "https://gisportal.co.madison.il.us/servera/rest/services/CCAO/Parcel_Owners/MapServer/0/query"
FIELDS = ("OBJECTID", "PIN", "NUM", "NUM_SUFF", "ST_PRE", "ST_NAME", "ST_TYPE", "ST_POST", "CITY", "STATE", "ZIP", "COMM", "SQFT", "ACRES")
COLUMNS = ("source_id", "state", "county", "source_parcel_id", "snapshot_year", "street_address", "city", "zip_code", "land_area", "land_area_unit", "source_hash")
SQL = f"""INSERT INTO public_property_snapshots ({','.join(COLUMNS)}) VALUES %s
ON CONFLICT(source_id,source_parcel_id,snapshot_year) DO UPDATE SET street_address=EXCLUDED.street_address,
 city=EXCLUDED.city,zip_code=EXCLUDED.zip_code,land_area=EXCLUDED.land_area,
 land_area_unit=EXCLUDED.land_area_unit,source_hash=EXCLUDED.source_hash,imported_at=NOW()
WHERE public_property_snapshots.source_hash<>EXCLUDED.source_hash"""


def parcel_id(value: Any) -> str | None:
    value = text_value(value)
    return f"IL:MADISON:{''.join(c for c in value.upper() if c.isalnum())}" if value else None


def address(row: dict[str, Any]) -> str | None:
    parts = [text_value(row.get(k)) for k in ("NUM", "NUM_SUFF", "ST_PRE", "ST_NAME", "ST_TYPE", "ST_POST")]
    return " ".join(p for p in parts if p) or None


def parse(row: dict[str, Any]) -> tuple[Any, ...] | None:
    identity = parcel_id(row.get("PIN"))
    if not identity:
        return None
    area = decimal_value(row.get("SQFT"))
    if area is None:
        acres = decimal_value(row.get("ACRES"))
        area = acres * Decimal(43560) if acres is not None else None
    if area is not None and not Decimal(0) <= area < Decimal("1000000000000"):
        area = None
    core = {"source_id": SOURCE_ID, "state": "IL", "county": "Madison",
            "source_parcel_id": identity, "snapshot_year": 2026,
            "street_address": address(row), "city": text_value(row.get("CITY")) or text_value(row.get("COMM")),
            "zip_code": text_value(row.get("ZIP")), "land_area": area, "land_area_unit": "square feet"}
    return tuple(core[n] for n in COLUMNS[:-1]) + (stable_hash(core),)


def pages(client: httpx.Client, size: int) -> Iterator[list[dict[str, Any]]]:
    after = 0
    while True:
        response = client.get(QUERY_URL, params={"where": f"OBJECTID>{after}", "outFields": ",".join(FIELDS),
                              "returnGeometry": "false", "orderByFields": "OBJECTID",
                              "resultRecordCount": size, "f": "json"})
        response.raise_for_status()
        payload = response.json()
        if payload.get("error"):
            raise RuntimeError(payload["error"])
        rows = [feature["attributes"] for feature in payload.get("features", [])]
        if not rows:
            break
        yield rows
        after = rows[-1]["OBJECTID"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--page-size", type=int, default=2000)
    parser.add_argument("--batch-size", type=int, default=10000)
    args = parser.parse_args()
    with warehouse_engine.begin() as connection:
        connection.execute(text("""INSERT INTO public_data_sources(source_id,state,county,source_name,source_url,access_method,coverage_notes,last_checked_at)
          VALUES(:id,'IL','Madison','Madison County Parcel Base',:url,'ArcGIS MapServer','Current PIN, situs and parcel area; owner and mailing fields excluded',NOW())
          ON CONFLICT(source_id) DO UPDATE SET last_checked_at=NOW(),updated_at=NOW()"""), {"id": SOURCE_ID, "url": SOURCE_PAGE})
    raw = warehouse_engine.raw_connection()
    loaded = 0
    batch: dict[str, tuple[Any, ...]] = {}
    try:
        cursor = raw.cursor()
        with httpx.Client(timeout=180, follow_redirects=True) as client:
            for page in pages(client, args.page_size):
                for source in page:
                    row = parse(source)
                    if row:
                        batch[row[3]] = row
                if len(batch) >= args.batch_size:
                    execute_values(cursor, SQL, list(batch.values()), page_size=args.batch_size)
                    loaded += len(batch); batch.clear(); raw.commit()
                    print(f"Madison parcels: {loaded:,}", flush=True)
        if batch:
            execute_values(cursor, SQL, list(batch.values()), page_size=args.batch_size)
            loaded += len(batch); raw.commit()
    finally:
        raw.close()
    print(f"complete Madison parcel snapshots={loaded:,}")


if __name__ == "__main__":
    main()
