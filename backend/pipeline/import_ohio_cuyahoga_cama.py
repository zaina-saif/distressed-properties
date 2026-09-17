"""Import Cuyahoga County's official public parcel/CAMA table.

Only situs, assessment, building-summary, and transfer fields are requested.
Owner, grantor/grantee, and mailing fields are deliberately excluded.
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from psycopg2.extras import execute_values
from sqlalchemy import text

from app.database.session import warehouse_engine
from pipeline.public_property_records import decimal_value, integer_value, stable_hash, text_value

SOURCE_ID = "oh_cuyahoga_cama"
COUNTY = "Cuyahoga"
SOURCE_PAGE = "https://gis.cuyahogacounty.gov/server/rest/services/CCGIS/Parcel_RP_CAMA_Table/MapServer/1"
QUERY_URL = f"{SOURCE_PAGE}/query"
FIELDS = ",".join((
    "OBJECTID", "PARCEL_ID", "PARCEL_YEAR", "TRANSFER_DATE", "SALES_AMOUNT",
    "PAR_ADDR", "PAR_PREDIR", "PAR_STREET", "PAR_SUFFIX", "PAR_UNIT",
    "PAR_CITY", "PAR_ZIP", "TAX_LUC", "TAX_LUC_DESCRIPTION", "PROPERTY_CLASS",
    "TAX_YEAR", "CERTIFIED_TAX_LAND", "CERTIFIED_TAX_BUILDING",
    "CERTIFIED_TAX_TOTAL", "TOTAL_RES_LIV_AREA", "TOTAL_RES_ROOMS",
    "TOTAL_COM_USE_AREA", "TOTAL_SQUARE_FT", "TOTAL_ACREAGE",
    "RES_BLDG_COUNT", "COM_BLDG_COUNT", "COM_LIVING_UNITS",
    "GARAGE_COUNT", "GARAGE_TYPE", "GARAGE_CAPACITY",
))
SNAPSHOT_COLUMNS = (
    "source_id", "state", "county", "source_parcel_id", "snapshot_year",
    "street_address", "city", "zip_code", "property_type", "land_use_code",
    "living_area", "land_area", "land_area_unit", "land_value",
    "improvement_value", "total_assessed_value", "source_hash",
)
SNAPSHOT_SQL = f"""
INSERT INTO public_property_snapshots ({','.join(SNAPSHOT_COLUMNS)}) VALUES %s
ON CONFLICT (source_id,source_parcel_id,snapshot_year) DO UPDATE SET
 street_address=EXCLUDED.street_address,city=EXCLUDED.city,zip_code=EXCLUDED.zip_code,
 property_type=EXCLUDED.property_type,land_use_code=EXCLUDED.land_use_code,
 living_area=EXCLUDED.living_area,land_area=EXCLUDED.land_area,
 land_area_unit=EXCLUDED.land_area_unit,land_value=EXCLUDED.land_value,
 improvement_value=EXCLUDED.improvement_value,
 total_assessed_value=EXCLUDED.total_assessed_value,
 source_hash=EXCLUDED.source_hash,imported_at=NOW()
WHERE public_property_snapshots.source_hash <> EXCLUDED.source_hash
"""
SALE_COLUMNS = (
    "source_id", "state", "county", "source_parcel_id", "transaction_id",
    "sale_date", "sale_price", "arms_length", "source_hash",
)
SALE_SQL = f"""
INSERT INTO public_property_sales ({','.join(SALE_COLUMNS)}) VALUES %s
ON CONFLICT (source_id,source_parcel_id,transaction_id) DO UPDATE SET
 sale_date=EXCLUDED.sale_date,sale_price=EXCLUDED.sale_price,
 source_hash=EXCLUDED.source_hash,imported_at=NOW()
WHERE public_property_sales.source_hash <> EXCLUDED.source_hash
"""


def parcel_id(row: dict[str, Any]) -> str | None:
    local = text_value(row.get("PARCEL_ID"))
    return f"39035-{local}" if local else None


def parse_snapshot(row: dict[str, Any]) -> tuple[Any, ...] | None:
    identity = parcel_id(row)
    year = integer_value(row.get("TAX_YEAR")) or integer_value(row.get("PARCEL_YEAR"))
    if not identity or not year:
        return None
    address = " ".join(filter(None, (
        text_value(row.get("PAR_ADDR")), text_value(row.get("PAR_PREDIR")),
        text_value(row.get("PAR_STREET")), text_value(row.get("PAR_SUFFIX")),
        text_value(row.get("PAR_UNIT")),
    ))) or None
    description = text_value(row.get("TAX_LUC_DESCRIPTION"))
    property_class = text_value(row.get("PROPERTY_CLASS"))
    living_area = integer_value(row.get("TOTAL_RES_LIV_AREA"))
    if not living_area:
        living_area = integer_value(row.get("TOTAL_COM_USE_AREA"))
    if not living_area:
        living_area = integer_value(row.get("TOTAL_SQUARE_FT"))
    acreage = decimal_value(row.get("TOTAL_ACREAGE"))
    if acreage is not None and acreage <= 0:
        acreage = None
    core = {
        "source_id": SOURCE_ID, "state": "OH", "county": COUNTY,
        "source_parcel_id": identity, "snapshot_year": year,
        "street_address": address, "city": text_value(row.get("PAR_CITY")),
        "zip_code": text_value(row.get("PAR_ZIP")),
        "property_type": description or property_class,
        "land_use_code": text_value(row.get("TAX_LUC")),
        "living_area": living_area, "land_area": acreage,
        "land_area_unit": "acres" if acreage is not None else None,
        "land_value": decimal_value(row.get("CERTIFIED_TAX_LAND")),
        "improvement_value": decimal_value(row.get("CERTIFIED_TAX_BUILDING")),
        "total_assessed_value": decimal_value(row.get("CERTIFIED_TAX_TOTAL")),
    }
    return tuple(core[name] for name in SNAPSHOT_COLUMNS[:-1]) + (stable_hash(core),)


def parse_sale(row: dict[str, Any]) -> tuple[Any, ...] | None:
    identity = parcel_id(row)
    milliseconds = integer_value(row.get("TRANSFER_DATE"))
    price = decimal_value(row.get("SALES_AMOUNT"))
    if not identity or not milliseconds or price is None or price <= 0:
        return None
    sale_date = datetime.fromtimestamp(milliseconds / 1000, tz=timezone.utc).date()
    transaction = stable_hash({"parcel": identity, "date": sale_date, "price": price})[:32]
    core = {
        "source_id": SOURCE_ID, "state": "OH", "county": COUNTY,
        "source_parcel_id": identity, "transaction_id": transaction,
        "sale_date": sale_date, "sale_price": price, "arms_length": None,
    }
    return tuple(core[name] for name in SALE_COLUMNS[:-1]) + (stable_hash(core),)


def request(client: httpx.Client, data: dict[str, Any]) -> dict[str, Any]:
    for attempt in range(8):
        try:
            response = client.post(QUERY_URL, data={**data, "f": "json"})
            response.raise_for_status()
            payload = response.json()
            if "error" in payload:
                raise RuntimeError(str(payload["error"]))
            return payload
        except (httpx.HTTPError, RuntimeError):
            if attempt == 7:
                raise
            time.sleep(min(2 ** attempt, 30))
    raise AssertionError("unreachable")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=5_000)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        ids = sorted(request(client, {"where": "1=1", "returnIdsOnly": "true"}).get("objectIds") or [])
        connection = warehouse_engine.raw_connection() if not args.dry_run else None
        snapshots = sales = 0
        try:
            cursor = connection.cursor() if connection else None
            for start in range(0, len(ids), args.batch_size):
                page_ids = ids[start:start + args.batch_size]
                payload = request(client, {
                    "objectIds": ",".join(map(str, page_ids)), "outFields": FIELDS,
                    "returnGeometry": "false", "orderByFields": "OBJECTID",
                })
                rows = [feature["attributes"] for feature in payload.get("features", [])]
                snapshot_items = [item for row in rows if (item := parse_snapshot(row))]
                sale_items = [item for row in rows if (item := parse_sale(row))]
                snapshot_batch = list({(item[3], item[4]): item for item in snapshot_items}.values())
                sale_batch = list({(item[3], item[4]): item for item in sale_items}.values())
                if cursor:
                    execute_values(cursor, SNAPSHOT_SQL, snapshot_batch, page_size=args.batch_size)
                    if sale_batch:
                        execute_values(cursor, SALE_SQL, sale_batch, page_size=args.batch_size)
                    connection.commit()
                snapshots += len(snapshot_batch); sales += len(sale_batch)
                print(f"Cuyahoga source={min(start + len(page_ids), len(ids)):,} snapshots={snapshots:,} sales={sales:,}", flush=True)
            if connection:
                with connection.cursor() as manifest:
                    manifest.execute("""
                        INSERT INTO public_import_files(source_id,file_name,file_url,row_count,status,completed_at)
                        VALUES(%s,'Cuyahoga CAMA',%s,%s,'completed',NOW())
                        ON CONFLICT(source_id,file_name) DO UPDATE SET
                          row_count=EXCLUDED.row_count,status='completed',completed_at=NOW()
                    """, (SOURCE_ID, SOURCE_PAGE, snapshots))
                connection.commit()
        finally:
            if connection:
                connection.close()
    print(f"complete Cuyahoga snapshots={snapshots:,} sales={sales:,}")


if __name__ == "__main__":
    with warehouse_engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO public_data_sources
              (source_id,state,county,source_name,source_url,access_method,coverage_notes,last_checked_at)
            VALUES (:id,'OH','Cuyahoga','Cuyahoga County Parcel RP CAMA',:url,'arcgis_rest',
              'Current CAMA assessment/building summary and latest parcel transfer; personal-name and mailing fields excluded',NOW())
            ON CONFLICT(source_id) DO UPDATE SET last_checked_at=NOW(),updated_at=NOW()
        """), {"id": SOURCE_ID, "url": SOURCE_PAGE})
    main()
