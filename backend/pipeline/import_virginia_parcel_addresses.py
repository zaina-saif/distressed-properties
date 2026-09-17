"""Import public Virginia parcel situs addresses keyed by VGIN QPID.

Only parcel ID, locality, situs address, city and ZIP are requested. Mailing and
owner fields are neither fetched nor stored. The feed supplements blank local-
schema snapshots without creating duplicate property snapshots.
"""
from __future__ import annotations

import argparse
import re
import time
from typing import Any, Iterator

import httpx
from psycopg2.extras import execute_values
from sqlalchemy import text

from app.database.session import warehouse_engine
from pipeline.import_virginia_local_schemas import parcel_identity
from pipeline.public_property_records import integer_value, stable_hash, text_value

SOURCE_ID = "va_dwr_public_parcel_addresses_2026"
SOURCE_PAGE = "https://services.dwr.virginia.gov/arcgis/rest/services/Projects/VA_Parcels/MapServer/0"
QUERY_URL = f"{SOURCE_PAGE}/query"
FIELDS = "OBJECTID,VGIN_QPID,VGIN_Locality_Name,Address,City,Zip"
COLUMNS = ("source_id", "state", "county", "source_parcel_id", "as_of_year",
           "street_address", "city", "zip_code", "house_number_unavailable", "source_hash")
SQL = f"""INSERT INTO public_parcel_addresses ({','.join(COLUMNS)}) VALUES %s
ON CONFLICT(source_id,source_parcel_id,as_of_year) DO UPDATE SET
 county=EXCLUDED.county,street_address=EXCLUDED.street_address,city=EXCLUDED.city,
 zip_code=EXCLUDED.zip_code,house_number_unavailable=EXCLUDED.house_number_unavailable,
 source_hash=EXCLUDED.source_hash,imported_at=NOW()
WHERE public_parcel_addresses.source_hash<>EXCLUDED.source_hash"""


def parse(attributes: dict[str, Any]) -> tuple[Any, ...] | None:
    identity = parcel_identity(attributes.get("VGIN_QPID"))
    county = text_value(attributes.get("VGIN_Locality_Name"))
    address = text_value(attributes.get("Address"))
    if not identity or not county or not address:
        return None
    zip_code = text_value(attributes.get("Zip"))
    if zip_code == "00000":
        zip_code = None
    core = {
        "source_id": SOURCE_ID, "state": "VA", "county": county,
        "source_parcel_id": identity, "as_of_year": 2026,
        "street_address": address, "city": text_value(attributes.get("City")),
        "zip_code": zip_code,
        "house_number_unavailable": re.match(r"^\d", address) is None,
    }
    return tuple(core[name] for name in COLUMNS[:-1]) + (stable_hash(core),)


def pages(client: httpx.Client, after_objectid: int, page_size: int) -> Iterator[tuple[int, list[dict[str, Any]]]]:
    after = after_objectid
    while True:
        params = {"where": f"Address IS NOT NULL AND OBJECTID>{after}",
                  "outFields": FIELDS, "returnGeometry": "false",
                  "orderByFields": "OBJECTID", "resultRecordCount": page_size, "f": "json"}
        for attempt in range(5):
            try:
                response = client.get(QUERY_URL, params=params)
                response.raise_for_status()
                payload = response.json()
                if "error" in payload:
                    raise ValueError(str(payload["error"]))
                rows = [item["attributes"] for item in payload.get("features", [])]
                break
            except (httpx.HTTPError, ValueError, KeyError):
                if attempt == 4:
                    raise
                time.sleep(2 ** attempt)
        if not rows:
            return
        last = integer_value(rows[-1].get("OBJECTID"))
        if last is None or last <= after:
            raise ValueError("Virginia address feed did not advance OBJECTID")
        yield last, rows
        after = last
        if len(rows) < page_size and not payload.get("exceededTransferLimit"):
            return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--after-objectid", type=int, default=0,
                        help="Resume from the last printed committed OBJECTID")
    parser.add_argument("--page-size", type=int, default=2000)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.page_size <= 2000:
        parser.error("--page-size must be between 1 and 2000")
    if not args.dry_run:
        with warehouse_engine.begin() as connection:
            connection.execute(text("""INSERT INTO public_data_sources
              (source_id,state,source_name,source_url,access_method,coverage_notes,last_checked_at)
              VALUES(:id,'VA','Virginia DWR public parcel situs addresses',:url,
              'ArcGIS public MapServer','Current 2026 VGIN QPID, situs address, city and ZIP only; no owner or mailing fields',NOW())
              ON CONFLICT(source_id) DO UPDATE SET last_checked_at=NOW(),updated_at=NOW()"""),
              {"id": SOURCE_ID, "url": SOURCE_PAGE})
    total = 0
    raw = warehouse_engine.raw_connection() if not args.dry_run else None
    try:
        with httpx.Client(timeout=120, follow_redirects=True) as client:
            for last, source_rows in pages(client, args.after_objectid, args.page_size):
                batch = {row[3]: row for item in source_rows if (row := parse(item)) is not None}
                if raw is not None and batch:
                    execute_values(raw.cursor(), SQL, list(batch.values()), page_size=1000)
                    raw.commit()
                total += len(batch)
                print(f"after_objectid={last} imported={total:,}", flush=True)
    finally:
        if raw is not None:
            raw.close()
    print(f"complete VA address records={total:,} dry_run={args.dry_run}")


if __name__ == "__main__":
    main()
