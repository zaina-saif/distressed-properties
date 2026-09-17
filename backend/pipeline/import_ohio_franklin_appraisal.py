"""Import Franklin County Auditor appraisal and complete sales-history files."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import tempfile
import zipfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator

import httpx
from psycopg2.extras import execute_values
from sqlalchemy import text

from app.database.session import warehouse_engine
from pipeline.public_property_records import decimal_value, integer_value, stable_hash, text_value

SOURCE_ID = "oh_franklin_appraisal_2026_08"
COUNTY = "Franklin"
SNAPSHOT_YEAR = 2026
ARCHIVE_URL = ("https://apps.franklincountyauditor.com/Outside_User_Files/2026/"
               "2026-08-15%20Appraisal/Tab-Delimited.zip")
SOURCE_PAGE = "https://auditor.franklincountyohio.gov/Auditor/FTP"
SNAPSHOT_COLUMNS = (
    "source_id", "state", "county", "source_parcel_id", "snapshot_year",
    "street_address", "property_type", "land_use_code", "year_built",
    "living_area", "bedrooms", "bathrooms", "land_value", "improvement_value",
    "market_value", "source_hash",
)
SNAPSHOT_SQL = f"""
INSERT INTO public_property_snapshots ({','.join(SNAPSHOT_COLUMNS)}) VALUES %s
ON CONFLICT (source_id,source_parcel_id,snapshot_year) DO UPDATE SET
 street_address=EXCLUDED.street_address,property_type=EXCLUDED.property_type,
 land_use_code=EXCLUDED.land_use_code,year_built=EXCLUDED.year_built,
 living_area=EXCLUDED.living_area,bedrooms=EXCLUDED.bedrooms,
 bathrooms=EXCLUDED.bathrooms,land_value=EXCLUDED.land_value,
 improvement_value=EXCLUDED.improvement_value,market_value=EXCLUDED.market_value,
 source_hash=EXCLUDED.source_hash,imported_at=NOW()
WHERE public_property_snapshots.source_hash <> EXCLUDED.source_hash
"""
SALE_COLUMNS = (
    "source_id", "state", "county", "source_parcel_id", "transaction_id",
    "sale_date", "sale_price", "conveyance_code", "arms_length", "source_hash",
)
SALE_SQL = f"""
INSERT INTO public_property_sales ({','.join(SALE_COLUMNS)}) VALUES %s
ON CONFLICT (source_id,source_parcel_id,transaction_id) DO UPDATE SET
 sale_date=EXCLUDED.sale_date,sale_price=EXCLUDED.sale_price,
 conveyance_code=EXCLUDED.conveyance_code,arms_length=EXCLUDED.arms_length,
 source_hash=EXCLUDED.source_hash,imported_at=NOW()
WHERE public_property_sales.source_hash <> EXCLUDED.source_hash
"""


def clean_row(row: dict[str, str]) -> dict[str, str]:
    return {(key or "").strip().lstrip("\ufeff"): value for key, value in row.items()}


def rows(archive: zipfile.ZipFile, member: str) -> Iterator[dict[str, str]]:
    with archive.open(member) as raw, io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace", newline="") as stream:
        for row in csv.DictReader(stream, delimiter="\t"):
            yield clean_row(row)


def state_parcel_id(local: Any) -> str | None:
    value = text_value(local)
    return f"39049-{value}" if value else None


def aggregate_dwellings(archive: zipfile.ZipFile) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows(archive, "Dwelling.txt"):
        identity = state_parcel_id(row.get("PARCEL ID"))
        if not identity:
            continue
        item = result.setdefault(identity, {"beds": Decimal(0), "baths": Decimal(0), "area": 0, "year": None})
        item["beds"] += decimal_value(row.get("RMBED")) or 0
        full = decimal_value(row.get("FIXBATH")) or 0
        half = decimal_value(row.get("FIXHALF")) or 0
        item["baths"] += full + half / Decimal(2)
        item["area"] += integer_value(row.get("SFLA")) or integer_value(row.get("ADJAREA")) or 0
        year = integer_value(row.get("YRBLT"))
        if year and (item["year"] is None or year < item["year"]):
            item["year"] = year
    return result


def parse_snapshot(row: dict[str, Any], dwelling: dict[str, Any] | None) -> tuple[Any, ...] | None:
    identity = state_parcel_id(row.get("PARCEL ID"))
    if not identity:
        return None
    number = text_value(row.get("ADRNOLOW"))
    address = " ".join(filter(None, (number, text_value(row.get("ADRDIR")),
                                      text_value(row.get("ADRSTR")), text_value(row.get("ADRSUF")),
                                      text_value(row.get("UNITNO"))))) or None
    dwelling = dwelling or {}
    land_use = text_value(row.get("LUC"))
    core = {
        "source_id": SOURCE_ID, "state": "OH", "county": COUNTY,
        "source_parcel_id": identity, "snapshot_year": SNAPSHOT_YEAR,
        "street_address": address, "property_type": text_value(row.get("PROPERTYCLASS")),
        "land_use_code": land_use, "year_built": dwelling.get("year"),
        "living_area": dwelling.get("area") or None,
        "bedrooms": dwelling.get("beds") or None, "bathrooms": dwelling.get("baths") or None,
        "land_value": decimal_value(row.get("COSTLAND")),
        "improvement_value": decimal_value(row.get("COSTIMP")),
        "market_value": decimal_value(row.get("COSTTOT")),
    }
    return tuple(core[name] for name in SNAPSHOT_COLUMNS[:-1]) + (stable_hash(core),)


def parse_sale(row: dict[str, Any]) -> tuple[Any, ...] | None:
    identity = state_parcel_id(row.get("PARCEL ID"))
    price = decimal_value(row.get("ADJPRICE")) or decimal_value(row.get("PRICE"))
    raw_date = text_value(row.get("SALEDT"))
    if not identity or price is None or price <= 0 or not raw_date:
        return None
    try:
        sale_date = datetime.strptime(raw_date, "%m/%d/%Y").date()
    except ValueError:
        return None
    instrument = text_value(row.get("INSTRUNO"))
    transaction = instrument or stable_hash({
        "parcel": identity, "date": sale_date, "price": price,
        "type": text_value(row.get("SALETYPE")), "instrument": text_value(row.get("INSTRUMENT")),
    })[:32]
    conditions = [value for key, value in row.items() if key.startswith("CONDSALE_")]
    valid = (text_value(row.get("VALID")) or "").upper()
    arms_length = False if any((value or "").strip().upper() == "Y" for value in conditions) else (
        True if valid.startswith("V") else None
    )
    conveyance = ";".join(filter(None, (text_value(row.get("SALETYPE")),
                                         text_value(row.get("INSTRUMENT")), valid or None))) or None
    core = {
        "source_id": SOURCE_ID, "state": "OH", "county": COUNTY,
        "source_parcel_id": identity, "transaction_id": transaction,
        "sale_date": sale_date, "sale_price": price,
        "conveyance_code": conveyance, "arms_length": arms_length,
    }
    return tuple(core[name] for name in SALE_COLUMNS[:-1]) + (stable_hash(core),)


def flush(cursor: Any, sql: str, items: list[tuple[Any, ...]], connection: Any) -> None:
    if items:
        execute_values(cursor, sql, items, page_size=len(items)); connection.commit()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--batch-size", type=int, default=5_000)
    args = parser.parse_args()
    temporary = args.archive is None
    path = args.archive
    checksum = hashlib.sha256()
    if path is None:
        handle = tempfile.NamedTemporaryFile(prefix="franklin_", suffix=".zip", delete=False)
        path = Path(handle.name); handle.close()
        with httpx.stream("GET", ARCHIVE_URL, follow_redirects=True, timeout=180) as response:
            response.raise_for_status()
            with path.open("wb") as output:
                for chunk in response.iter_bytes(1024 * 1024):
                    output.write(chunk); checksum.update(chunk)
    try:
        with zipfile.ZipFile(path) as archive:
            dwellings = aggregate_dwellings(archive)
            connection = warehouse_engine.raw_connection()
            snapshots = sales = 0
            try:
                cursor = connection.cursor()
                batch: dict[tuple[Any, ...], tuple[Any, ...]] = {}
                for row in rows(archive, "Parcel.txt"):
                    parsed = parse_snapshot(row, dwellings.get(state_parcel_id(row.get("PARCEL ID")) or ""))
                    if parsed:
                        batch[(parsed[3], parsed[4])] = parsed
                    if len(batch) >= args.batch_size:
                        flush(cursor, SNAPSHOT_SQL, list(batch.values()), connection); snapshots += len(batch); batch.clear()
                flush(cursor, SNAPSHOT_SQL, list(batch.values()), connection); snapshots += len(batch)
                for member in ("Sales010.txt", "Sales020-277.txt", "Sales410-610.txt"):
                    sale_batch: dict[tuple[Any, ...], tuple[Any, ...]] = {}
                    for row in rows(archive, member):
                        parsed = parse_sale(row)
                        if parsed:
                            sale_batch[(parsed[3], parsed[4])] = parsed
                        if len(sale_batch) >= args.batch_size:
                            flush(cursor, SALE_SQL, list(sale_batch.values()), connection); sales += len(sale_batch); sale_batch.clear()
                    flush(cursor, SALE_SQL, list(sale_batch.values()), connection); sales += len(sale_batch)
                with connection.cursor() as manifest:
                    manifest.execute("""
                        INSERT INTO public_import_files(source_id,file_name,file_url,file_size,sha256,row_count,status,completed_at)
                        VALUES(%s,'2026-08-15 Appraisal',%s,%s,%s,%s,'completed',NOW())
                        ON CONFLICT(source_id,file_name) DO UPDATE SET row_count=EXCLUDED.row_count,status='completed',completed_at=NOW()
                    """, (SOURCE_ID, ARCHIVE_URL, path.stat().st_size,
                           checksum.hexdigest() or None, snapshots + sales))
                connection.commit()
            finally:
                connection.close()
        print(f"complete Franklin snapshots={snapshots:,} sales={sales:,}")
    finally:
        if temporary:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    with warehouse_engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO public_data_sources(source_id,state,county,source_name,source_url,access_method,coverage_notes,last_checked_at)
            VALUES(:id,'OH','Franklin','Franklin County Auditor Appraisal Outside User Files',:url,'zip_tsv',
              '2026 appraisal snapshot and full published sales tables; owner fields excluded',NOW())
            ON CONFLICT(source_id) DO UPDATE SET last_checked_at=NOW(),updated_at=NOW()
        """), {"id": SOURCE_ID, "url": SOURCE_PAGE})
    main()
