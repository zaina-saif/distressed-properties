"""Import Summit County Fiscal Office public CAMA property and sales exports."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import tempfile
import zipfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator

import httpx
from psycopg2.extras import execute_values
from sqlalchemy import text

from app.database.session import warehouse_engine
from pipeline.public_property_records import decimal_value, integer_value, stable_hash, text_value

SOURCE_ID = "oh_summit_cama_2026_04"
COUNTY = "Summit"
SNAPSHOT_YEAR = 2026
SOURCE_PAGE = "https://fiscaloffice.summitoh.net/data-downloads"
BASE_URL = "https://fiscaloffice.summitoh.net/sites/default/files/assets/forms"
FILES = {
    "assessment": ("SC703_ASMT.ZIP", "SC703_ASMT.CSV"),
    "appraisal": ("SC704_APRVAL.ZIP", "SC704_APRVAL.CSV"),
    "parcel": ("SC705_PARDAT.ZIP", "SC705_PARDAT.CSV"),
    "sales": ("SC706_SALES.ZIP", "SC706_SALES.CSV"),
    "land": ("SC709_LAND.zip", "SC709_LAND.CSV"),
    "dwelling": ("SC710_DWELL.zip", "SC710_DWELL.CSV"),
}
SNAPSHOT_COLUMNS = (
    "source_id", "state", "county", "source_parcel_id", "snapshot_year",
    "street_address", "city", "zip_code", "property_type", "land_use_code",
    "year_built", "living_area", "land_area", "land_area_unit", "bedrooms",
    "bathrooms", "land_value", "improvement_value", "total_assessed_value",
    "market_value", "source_hash",
)
SNAPSHOT_SQL = f"""
INSERT INTO public_property_snapshots ({','.join(SNAPSHOT_COLUMNS)}) VALUES %s
ON CONFLICT (source_id,source_parcel_id,snapshot_year) DO UPDATE SET
 street_address=EXCLUDED.street_address,city=EXCLUDED.city,zip_code=EXCLUDED.zip_code,
 property_type=EXCLUDED.property_type,land_use_code=EXCLUDED.land_use_code,
 year_built=EXCLUDED.year_built,living_area=EXCLUDED.living_area,
 land_area=EXCLUDED.land_area,land_area_unit=EXCLUDED.land_area_unit,
 bedrooms=EXCLUDED.bedrooms,bathrooms=EXCLUDED.bathrooms,
 land_value=EXCLUDED.land_value,improvement_value=EXCLUDED.improvement_value,
 total_assessed_value=EXCLUDED.total_assessed_value,market_value=EXCLUDED.market_value,
 source_hash=EXCLUDED.source_hash,imported_at=NOW()
WHERE public_property_snapshots.source_hash <> EXCLUDED.source_hash
"""
SALE_COLUMNS = (
    "source_id", "state", "county", "source_parcel_id", "transaction_id",
    "sale_date", "sale_price", "recording_date", "conveyance_code",
    "arms_length", "source_hash",
)
SALE_SQL = f"""
INSERT INTO public_property_sales ({','.join(SALE_COLUMNS)}) VALUES %s
ON CONFLICT (source_id,source_parcel_id,transaction_id) DO UPDATE SET
 sale_date=EXCLUDED.sale_date,sale_price=EXCLUDED.sale_price,
 recording_date=EXCLUDED.recording_date,conveyance_code=EXCLUDED.conveyance_code,
 arms_length=EXCLUDED.arms_length,source_hash=EXCLUDED.source_hash,imported_at=NOW()
WHERE public_property_sales.source_hash <> EXCLUDED.source_hash
"""


def clean_row(row: dict[str, str]) -> dict[str, str]:
    return {(key or "").strip().lstrip("\ufeff"): value for key, value in row.items()}


def rows(path: Path, member: str) -> Iterator[dict[str, str]]:
    with zipfile.ZipFile(path) as archive, archive.open(member) as raw:
        stream = io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace", newline="")
        for row in csv.DictReader(stream):
            yield clean_row(row)


def state_parcel_id(local: Any) -> str | None:
    value = text_value(local)
    return f"39153-{value}" if value else None


def parse_date(value: Any):
    value = text_value(value)
    if not value:
        return None
    try:
        return datetime.strptime(value, "%d-%b-%Y").date()
    except ValueError:
        return None


def aggregate_dwellings(source: Iterator[dict[str, str]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in source:
        identity = state_parcel_id(row.get("PARCEL"))
        if not identity:
            continue
        item = result.setdefault(identity, {"beds": Decimal(0), "baths": Decimal(0), "area": 0, "year": None})
        item["beds"] += decimal_value(row.get("BD")) or 0
        item["baths"] += ((decimal_value(row.get("BTH")) or Decimal(0))
                          + (decimal_value(row.get("FXH")) or Decimal(0)) / Decimal(2))
        item["area"] += integer_value(row.get("SFLA")) or 0
        year = integer_value(row.get("YRBLT"))
        if year and (item["year"] is None or year < item["year"]):
            item["year"] = year
    return result


def keyed_values(source: Iterator[dict[str, str]]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for row in source:
        identity = state_parcel_id(row.get("PARCEL"))
        if identity:
            result[identity] = row
    return result


def aggregate_land(source: Iterator[dict[str, str]]) -> dict[str, Decimal]:
    result: dict[str, Decimal] = {}
    for row in source:
        identity = state_parcel_id(row.get("PARCEL"))
        acres = decimal_value(row.get("ACRE"))
        if identity and acres and acres > 0:
            result[identity] = result.get(identity, Decimal(0)) + acres
    return result


def parse_snapshot(row: dict[str, Any], dwelling: dict[str, Any] | None,
                   assessment: dict[str, Any] | None, appraisal: dict[str, Any] | None,
                   acres: Decimal | None) -> tuple[Any, ...] | None:
    identity = state_parcel_id(row.get("PARCEL"))
    if not identity:
        return None
    dwelling, assessment, appraisal = dwelling or {}, assessment or {}, appraisal or {}
    address = " ".join(filter(None, (
        text_value(row.get("ADRNO")), text_value(row.get("ADRADD")), text_value(row.get("ADRDIR")),
        text_value(row.get("ADRSTR")), text_value(row.get("ADRSUF")), text_value(row.get("ADRSUF2")),
    ))) or None
    assessed_land = decimal_value(assessment.get("APRLAND"))
    assessed_building = decimal_value(assessment.get("APRBLDG"))
    market_land = decimal_value(appraisal.get("APRLAND")) or decimal_value(appraisal.get("LANDVAL"))
    market_building = decimal_value(appraisal.get("APRBLDG")) or decimal_value(appraisal.get("BLDGVAL"))
    market_total = decimal_value(appraisal.get("MKTVAL")) or decimal_value(appraisal.get("COSTVAL"))
    if market_total is None and (market_land is not None or market_building is not None):
        market_total = (market_land or 0) + (market_building or 0)
    core = {
        "source_id": SOURCE_ID, "state": "OH", "county": COUNTY,
        "source_parcel_id": identity, "snapshot_year": SNAPSHOT_YEAR,
        "street_address": address, "city": text_value(row.get("CITY")),
        "zip_code": text_value(row.get("ZIPCD")), "property_type": text_value(row.get("CLASS")),
        "land_use_code": text_value(row.get("LUC")), "year_built": dwelling.get("year"),
        "living_area": dwelling.get("area") or None, "land_area": acres,
        "land_area_unit": "acres" if acres is not None else None,
        "bedrooms": dwelling.get("beds") or None, "bathrooms": dwelling.get("baths") or None,
        "land_value": market_land, "improvement_value": market_building,
        "total_assessed_value": ((assessed_land or 0) + (assessed_building or 0))
        if assessed_land is not None or assessed_building is not None else None,
        "market_value": market_total,
    }
    return tuple(core[name] for name in SNAPSHOT_COLUMNS[:-1]) + (stable_hash(core),)


def parse_sale(row: dict[str, Any]) -> tuple[Any, ...] | None:
    identity = state_parcel_id(row.get("PARCEL"))
    sale_date = parse_date(row.get("SALEDATE"))
    price = decimal_value(row.get("PRICE"))
    if (not identity or not sale_date or sale_date < date(1800, 1, 1)
            or sale_date > date.today() or price is None or price <= 0):
        return None
    transaction = text_value(row.get("TRANSNO")) or stable_hash({
        "parcel": identity, "date": sale_date, "price": price,
        "book": text_value(row.get("BOOK")), "page": text_value(row.get("PAGE")),
    })[:32]
    # SALEVAL is retained as a code; no undocumented code is labeled arm's-length.
    conveyance = ";".join(filter(None, (
        text_value(row.get("SOURCECODE")), text_value(row.get("SALETYPE")), text_value(row.get("SALEVAL")),
    ))) or None
    core = {
        "source_id": SOURCE_ID, "state": "OH", "county": COUNTY,
        "source_parcel_id": identity, "transaction_id": transaction,
        "sale_date": sale_date, "sale_price": price, "recording_date": parse_date(row.get("TRNDTE")),
        "conveyance_code": conveyance, "arms_length": None,
    }
    return tuple(core[name] for name in SALE_COLUMNS[:-1]) + (stable_hash(core),)


def flush(cursor: Any, sql: str, items: list[tuple[Any, ...]], connection: Any) -> None:
    if items:
        execute_values(cursor, sql, items, page_size=len(items))
        connection.commit()


def download_archives(directory: Path) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for kind, (filename, _) in FILES.items():
        path = directory / filename
        if not path.exists():
            with httpx.stream("GET", f"{BASE_URL}/{filename}", follow_redirects=True, timeout=180) as response:
                response.raise_for_status()
                with path.open("wb") as output:
                    for chunk in response.iter_bytes(1024 * 1024):
                        output.write(chunk)
        paths[kind] = path
    return paths


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive-dir", type=Path)
    parser.add_argument("--batch-size", type=int, default=5_000)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="summit_cama_") if args.archive_dir is None else _null_context(args.archive_dir) as raw_dir:
        directory = Path(raw_dir)
        paths = download_archives(directory)
        dwellings = aggregate_dwellings(rows(paths["dwelling"], FILES["dwelling"][1]))
        assessments = keyed_values(rows(paths["assessment"], FILES["assessment"][1]))
        appraisals = keyed_values(rows(paths["appraisal"], FILES["appraisal"][1]))
        land = aggregate_land(rows(paths["land"], FILES["land"][1]))
        connection = warehouse_engine.raw_connection()
        snapshots = sales = 0
        try:
            cursor = connection.cursor()
            batch: dict[tuple[Any, ...], tuple[Any, ...]] = {}
            for row in rows(paths["parcel"], FILES["parcel"][1]):
                identity = state_parcel_id(row.get("PARCEL"))
                parsed = parse_snapshot(row, dwellings.get(identity or ""), assessments.get(identity or ""),
                                        appraisals.get(identity or ""), land.get(identity or ""))
                if parsed:
                    batch[(parsed[3], parsed[4])] = parsed
                if len(batch) >= args.batch_size:
                    flush(cursor, SNAPSHOT_SQL, list(batch.values()), connection); snapshots += len(batch); batch.clear()
            flush(cursor, SNAPSHOT_SQL, list(batch.values()), connection); snapshots += len(batch)
            sale_batch: dict[tuple[Any, ...], tuple[Any, ...]] = {}
            for row in rows(paths["sales"], FILES["sales"][1]):
                parsed = parse_sale(row)
                if parsed:
                    sale_batch[(parsed[3], parsed[4])] = parsed
                if len(sale_batch) >= args.batch_size:
                    flush(cursor, SALE_SQL, list(sale_batch.values()), connection); sales += len(sale_batch); sale_batch.clear()
            flush(cursor, SALE_SQL, list(sale_batch.values()), connection); sales += len(sale_batch)
            with connection.cursor() as manifest:
                for kind, path in paths.items():
                    digest = hashlib.sha256(path.read_bytes()).hexdigest()
                    manifest.execute("""
                        INSERT INTO public_import_files(source_id,file_name,file_url,file_size,sha256,row_count,status,completed_at)
                        VALUES(%s,%s,%s,%s,%s,%s,'completed',NOW())
                        ON CONFLICT(source_id,file_name) DO UPDATE SET file_size=EXCLUDED.file_size,
                          sha256=EXCLUDED.sha256,row_count=EXCLUDED.row_count,status='completed',completed_at=NOW()
                    """, (SOURCE_ID, path.name, f"{BASE_URL}/{path.name}", path.stat().st_size,
                           digest, snapshots if kind == "parcel" else sales if kind == "sales" else 0))
            connection.commit()
        finally:
            connection.close()
    print(f"complete Summit snapshots={snapshots:,} sales={sales:,}")


class _null_context:
    def __init__(self, value: Path): self.value = value
    def __enter__(self): return self.value
    def __exit__(self, *_: Any): return False


if __name__ == "__main__":
    with warehouse_engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO public_data_sources(source_id,state,county,source_name,source_url,access_method,coverage_notes,last_checked_at)
            VALUES(:id,'OH','Summit','Summit County Fiscal Office CAMA exports',:url,'zip_csv',
              'April 2026 current CAMA snapshot and parcel-level sales history; owner and mailing fields excluded',NOW())
            ON CONFLICT(source_id) DO UPDATE SET last_checked_at=NOW(),updated_at=NOW()
        """), {"id": SOURCE_ID, "url": SOURCE_PAGE})
    main()
