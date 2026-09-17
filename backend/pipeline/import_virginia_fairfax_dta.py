"""Import Fairfax County's public Tax Administration real-estate tables."""
from __future__ import annotations

import argparse
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Iterator

import httpx
from psycopg2.extras import execute_values
from sqlalchemy import text

from app.database.session import warehouse_engine
from pipeline.public_property_records import decimal_value, integer_value, stable_hash, text_value

SOURCE_ID = "va_fairfax_dta_2026"
SOURCE_PAGE = "https://www.fairfaxcounty.gov/maps/gis-faq"
ROOT = "https://services1.arcgis.com/ioennV6PpG5Xodq0/ArcGIS/rest/services"
TABLES = {
    "sales": f"{ROOT}/OpenData_A5/FeatureServer/1",
    "parcel": f"{ROOT}/OpenData_A6/FeatureServer/1",
    "assessment": f"{ROOT}/OpenData_A6/FeatureServer/2",
    "land": f"{ROOT}/OpenData_A6/FeatureServer/3",
    "dwelling": f"{ROOT}/OpenData_A7/FeatureServer/2",
}
FIELDS = {
    "sales": "OBJECTID,PARID,TAXYR,SALEDT,PRICE,BOOK,PAGE,SALEVAL_DESC",
    "parcel": "OBJECTID,PARID,TAXYR,LOCATION_DESC,STREET1_DESC,LUC_DESC,ZONING_DESC",
    "assessment": "OBJECTID,PARID,TAXYR,APRLAND,APRBLDG,APRTOT,PRILAND,PRIBLDG,PRITOT,FLAG4_DESC",
    "land": "OBJECTID,PARID,TAXYR,LLINE,SF,ACRES,CODE_DESC",
    "dwelling": "OBJECTID,PARID,STYLE_DESC,YRBLT,RMBED,FIXBATH,FIXHALF,SFLA,EditDate",
}
PAGE_SIZE = 1_000
SNAPSHOT_COLUMNS = (
    "source_id", "state", "county", "source_parcel_id", "snapshot_year", "street_address",
    "property_type", "land_use_code", "year_built", "living_area", "land_area",
    "land_area_unit", "bedrooms", "bathrooms", "land_value", "improvement_value",
    "total_assessed_value", "market_value", "source_updated_at", "source_hash",
)
SNAPSHOT_SQL = f"""
INSERT INTO public_property_snapshots ({','.join(SNAPSHOT_COLUMNS)}) VALUES %s
ON CONFLICT (source_id,source_parcel_id,snapshot_year) DO UPDATE SET
 street_address=EXCLUDED.street_address,property_type=EXCLUDED.property_type,
 land_use_code=EXCLUDED.land_use_code,year_built=EXCLUDED.year_built,
 living_area=EXCLUDED.living_area,land_area=EXCLUDED.land_area,
 land_area_unit=EXCLUDED.land_area_unit,bedrooms=EXCLUDED.bedrooms,
 bathrooms=EXCLUDED.bathrooms,land_value=EXCLUDED.land_value,
 improvement_value=EXCLUDED.improvement_value,total_assessed_value=EXCLUDED.total_assessed_value,
 market_value=EXCLUDED.market_value,source_updated_at=EXCLUDED.source_updated_at,
 source_hash=EXCLUDED.source_hash,imported_at=NOW()
WHERE public_property_snapshots.source_hash <> EXCLUDED.source_hash
"""
SALE_COLUMNS = ("source_id", "state", "county", "source_parcel_id", "transaction_id",
                "sale_date", "sale_price", "conveyance_code", "arms_length", "source_hash")
SALE_SQL = f"""
INSERT INTO public_property_sales ({','.join(SALE_COLUMNS)}) VALUES %s
ON CONFLICT (source_id,source_parcel_id,transaction_id) DO UPDATE SET
 sale_date=EXCLUDED.sale_date,sale_price=EXCLUDED.sale_price,
 conveyance_code=EXCLUDED.conveyance_code,arms_length=EXCLUDED.arms_length,
 source_hash=EXCLUDED.source_hash,imported_at=NOW()
WHERE public_property_sales.source_hash <> EXCLUDED.source_hash
"""


def request_json(client: httpx.Client, url: str, data: dict[str, Any]) -> dict[str, Any]:
    for attempt in range(10):
        try:
            response = client.post(url, data=data)
            response.raise_for_status()
            payload = response.json()
            if "error" in payload:
                raise RuntimeError(str(payload["error"]))
            return payload
        except (httpx.HTTPError, RuntimeError):
            if attempt == 9:
                raise
            time.sleep(min(2 ** attempt, 30))
    raise AssertionError("unreachable")


def table_rows(client: httpx.Client, kind: str, workers: int) -> Iterator[dict[str, Any]]:
    url = f"{TABLES[kind]}/query"
    ids = sorted(request_json(client, url, {"where": "1=1", "returnIdsOnly": "true", "f": "json"}).get("objectIds") or [])
    pages = [ids[start:start + PAGE_SIZE] for start in range(0, len(ids), PAGE_SIZE)]

    def fetch(page: list[int]) -> list[dict[str, Any]]:
        payload = request_json(client, url, {"objectIds": ",".join(map(str, page)),
            "outFields": FIELDS[kind], "returnGeometry": "false", "orderByFields": "OBJECTID", "f": "json"})
        features = payload.get("features", [])
        if len(features) != len(page):
            raise RuntimeError(f"Fairfax {kind}: expected {len(page)} rows, received {len(features)}")
        return [feature["attributes"] for feature in features]

    with ThreadPoolExecutor(max_workers=workers) as executor:
        for rows in executor.map(fetch, pages):
            yield from rows


def parcel_id(value: Any) -> str | None:
    value = text_value(value)
    return f"51059-{value}" if value else None


def epoch_date(value: Any) -> date | None:
    if not isinstance(value, (int, float)):
        return None
    parsed = datetime.fromtimestamp(value / 1000, tz=timezone.utc).date()
    return parsed if date(1800, 1, 1) <= parsed <= date.today() else None


def aggregate_dwellings(rows: Iterator[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        identity = parcel_id(row.get("PARID"))
        if not identity:
            continue
        item = result.setdefault(identity, {"beds": Decimal(0), "baths": Decimal(0), "area": 0,
                                            "year": None, "style": None, "updated": None})
        item["beds"] += decimal_value(row.get("RMBED")) or 0
        item["baths"] += (decimal_value(row.get("FIXBATH")) or Decimal(0)) + (decimal_value(row.get("FIXHALF")) or Decimal(0)) / Decimal(2)
        item["area"] += integer_value(row.get("SFLA")) or 0
        year = integer_value(row.get("YRBLT"))
        if year and 1600 <= year <= date.today().year + 1 and (item["year"] is None or year < item["year"]): item["year"] = year
        item["style"] = item["style"] or text_value(row.get("STYLE_DESC"))
        updated = row.get("EditDate")
        if isinstance(updated, (int, float)) and (item["updated"] is None or updated > item["updated"]): item["updated"] = updated
    return result


def aggregate_land(rows: Iterator[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        identity = parcel_id(row.get("PARID"))
        if not identity:
            continue
        item = result.setdefault(identity, {"acres": Decimal(0), "sf": Decimal(0), "code": None})
        item["acres"] += decimal_value(row.get("ACRES")) or 0
        item["sf"] += decimal_value(row.get("SF")) or 0
        item["code"] = item["code"] or text_value(row.get("CODE_DESC"))
    return result


def keyed(rows: Iterator[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result = {}
    for row in rows:
        identity = parcel_id(row.get("PARID"))
        if identity:
            result[identity] = row
    return result


def parse_snapshot(row: dict[str, Any], parcel: dict[str, Any] | None,
                   dwelling: dict[str, Any] | None, land: dict[str, Any] | None) -> tuple[Any, ...] | None:
    identity = parcel_id(row.get("PARID"))
    if not identity:
        return None
    parcel, dwelling, land = parcel or {}, dwelling or {}, land or {}
    acres, square_feet = land.get("acres") or None, land.get("sf") or None
    land_area, land_unit = (acres, "acres") if acres else ((square_feet, "square feet") if square_feet else (None, None))
    year = integer_value(row.get("TAXYR")) or 2026
    core = {
        "source_id": SOURCE_ID, "state": "VA", "county": "Fairfax County",
        "source_parcel_id": identity, "snapshot_year": year,
        "street_address": text_value(parcel.get("LOCATION_DESC")) or text_value(parcel.get("STREET1_DESC")),
        "property_type": dwelling.get("style") or text_value(parcel.get("LUC_DESC")),
        "land_use_code": text_value(parcel.get("LUC_DESC")) or land.get("code"),
        "year_built": dwelling.get("year"), "living_area": dwelling.get("area") or None,
        "land_area": land_area, "land_area_unit": land_unit,
        "bedrooms": dwelling.get("beds") or None, "bathrooms": dwelling.get("baths") or None,
        "land_value": decimal_value(row.get("APRLAND")), "improvement_value": decimal_value(row.get("APRBLDG")),
        "total_assessed_value": decimal_value(row.get("APRTOT")), "market_value": decimal_value(row.get("APRTOT")),
        "source_updated_at": datetime.fromtimestamp(dwelling["updated"] / 1000, tz=timezone.utc) if dwelling.get("updated") else None,
    }
    return tuple(core[name] for name in SNAPSHOT_COLUMNS[:-1]) + (stable_hash(core),)


def parse_sale(row: dict[str, Any]) -> tuple[Any, ...] | None:
    identity, sale_date = parcel_id(row.get("PARID")), epoch_date(row.get("SALEDT"))
    price = decimal_value(row.get("PRICE"))
    if not identity or not sale_date or price is None or price <= 0:
        return None
    book, page, validity = text_value(row.get("BOOK")), text_value(row.get("PAGE")), text_value(row.get("SALEVAL_DESC"))
    transaction = ":".join(filter(None, (book, page))) or stable_hash({"parcel": identity, "date": sale_date, "price": price})[:32]
    normalized_validity = (validity or "").casefold()
    arms_length = True if "valid and verified" in normalized_validity else False if validity else None
    core = {"source_id": SOURCE_ID, "state": "VA", "county": "Fairfax County",
            "source_parcel_id": identity, "transaction_id": transaction, "sale_date": sale_date,
            "sale_price": price, "conveyance_code": validity, "arms_length": arms_length}
    return tuple(core[name] for name in SALE_COLUMNS[:-1]) + (stable_hash(core),)


def load_batches(rows: Iterator[tuple[Any, ...]], sql: str, batch_size: int,
                 key: Callable[[tuple[Any, ...]], Any]) -> int:
    connection = warehouse_engine.raw_connection(); loaded = 0
    try:
        cursor = connection.cursor(); batch = {}
        for row in rows:
            batch[key(row)] = row
            if len(batch) >= batch_size:
                execute_values(cursor, sql, list(batch.values()), page_size=batch_size); connection.commit()
                loaded += len(batch); batch.clear(); print(f"Fairfax loaded={loaded:,}", flush=True)
        if batch:
            execute_values(cursor, sql, list(batch.values()), page_size=batch_size); connection.commit(); loaded += len(batch)
    finally:
        connection.close()
    return loaded


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=5_000)
    args = parser.parse_args()
    with warehouse_engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO public_data_sources(source_id,state,county,source_name,source_url,access_method,coverage_notes,last_checked_at)
            VALUES(:id,'VA','Fairfax County','Fairfax County DTA Real Estate Open Data',:url,'arcgis_rest',
              'Weekly parcel, assessment, dwelling, land and all-sales tables; owner and party names excluded',NOW())
            ON CONFLICT(source_id) DO UPDATE SET last_checked_at=NOW(),updated_at=NOW()
        """), {"id": SOURCE_ID, "url": SOURCE_PAGE})
    with httpx.Client(timeout=120, follow_redirects=True, headers={"User-Agent": "Public-Property-AVM/1.0"}) as client:
        parcels = keyed(table_rows(client, "parcel", args.workers))
        dwellings = aggregate_dwellings(table_rows(client, "dwelling", args.workers))
        land = aggregate_land(table_rows(client, "land", args.workers))
        snapshots = load_batches((parsed for row in table_rows(client, "assessment", args.workers)
                                  if (parsed := parse_snapshot(row, parcels.get(parcel_id(row.get("PARID")) or ""),
                                                              dwellings.get(parcel_id(row.get("PARID")) or ""),
                                                              land.get(parcel_id(row.get("PARID")) or "")))),
                                 SNAPSHOT_SQL, args.batch_size, lambda row: (row[3], row[4]))
        sales = load_batches((parsed for row in table_rows(client, "sales", args.workers)
                              if (parsed := parse_sale(row))), SALE_SQL, args.batch_size,
                             lambda row: (row[3], row[4]))
    with warehouse_engine.begin() as connection:
        for kind in TABLES:
            count = snapshots if kind == "assessment" else sales if kind == "sales" else 0
            connection.execute(text("""
                INSERT INTO public_import_files(source_id,file_name,file_url,row_count,status,completed_at)
                VALUES(:source,:name,:url,:rows,'completed',NOW())
                ON CONFLICT(source_id,file_name) DO UPDATE SET row_count=EXCLUDED.row_count,status='completed',completed_at=NOW()
            """), {"source": SOURCE_ID, "name": kind, "url": TABLES[kind], "rows": count})
    print(f"complete Fairfax snapshots={snapshots:,} sales={sales:,}")


if __name__ == "__main__":
    main()
