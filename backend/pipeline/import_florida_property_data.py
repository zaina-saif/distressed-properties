"""Import Florida DOR 2026 preliminary NAL and SDF county files.

The statewide standardized rolls are discovered from the official SharePoint
library. ZIP files are processed one county at a time and immediately deleted.
Owner, fiduciary, legal-description, exemption, and mailing fields are ignored.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import tempfile
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import quote

import httpx
from psycopg2.extras import execute_values
from sqlalchemy import text

from app.database.session import warehouse_engine
from pipeline.public_property_records import decimal_value, integer_value, stable_hash, text_value

BASE_URL = "https://www.floridarevenue.com"
SHAREPOINT = f"{BASE_URL}/property/dataportal"
ROLL_ROOT = "/property/dataportal/Documents/PTO Data Portal/Tax Roll Data Files"
ROLL_VERSION = "2026P"
NAL_SOURCE_ID = "fl_dor_nal_2026p"
SDF_SOURCE_ID = "fl_dor_sdf_2026p"
SOURCE_PAGE = "https://www.floridarevenue.com/property/Pages/DataPortal_RequestAssessmentRollGISData.aspx"
MIGRATION = Path(__file__).resolve().parents[1] / "migrations/020_florida_import_support.sql"

COUNTIES = {
    "11": "Alachua", "12": "Baker", "13": "Bay", "14": "Bradford",
    "15": "Brevard", "16": "Broward", "17": "Calhoun", "18": "Charlotte",
    "19": "Citrus", "20": "Clay", "21": "Collier", "22": "Columbia",
    "23": "Miami-Dade", "24": "DeSoto", "25": "Dixie", "26": "Duval",
    "27": "Escambia", "28": "Flagler", "29": "Franklin", "30": "Gadsden",
    "31": "Gilchrist", "32": "Glades", "33": "Gulf", "34": "Hamilton",
    "35": "Hardee", "36": "Hendry", "37": "Hernando", "38": "Highlands",
    "39": "Hillsborough", "40": "Holmes", "41": "Indian River", "42": "Jackson",
    "43": "Jefferson", "44": "Lafayette", "45": "Lake", "46": "Lee",
    "47": "Leon", "48": "Levy", "49": "Liberty", "50": "Madison",
    "51": "Manatee", "52": "Marion", "53": "Martin", "54": "Monroe",
    "55": "Nassau", "56": "Okaloosa", "57": "Okeechobee", "58": "Orange",
    "59": "Osceola", "60": "Palm Beach", "61": "Pasco", "62": "Pinellas",
    "63": "Polk", "64": "Putnam", "65": "Saint Johns", "66": "Saint Lucie",
    "67": "Santa Rosa", "68": "Sarasota", "69": "Seminole", "70": "Sumter",
    "71": "Suwannee", "72": "Taylor", "73": "Union", "74": "Volusia",
    "75": "Wakulla", "76": "Walton", "77": "Washington",
}

SNAPSHOT_COLUMNS = (
    "source_id", "state", "county", "source_parcel_id", "snapshot_year",
    "street_address", "city", "zip_code", "property_type", "land_use_code",
    "year_built", "living_area", "land_area", "land_area_unit", "land_value",
    "improvement_value", "total_assessed_value", "market_value", "source_hash",
)
SNAPSHOT_SQL = f"""
INSERT INTO public_property_snapshots ({','.join(SNAPSHOT_COLUMNS)}) VALUES %s
ON CONFLICT (source_id,source_parcel_id,snapshot_year) DO UPDATE SET
 county=EXCLUDED.county,street_address=EXCLUDED.street_address,city=EXCLUDED.city,
 zip_code=EXCLUDED.zip_code,property_type=EXCLUDED.property_type,
 land_use_code=EXCLUDED.land_use_code,year_built=EXCLUDED.year_built,
 living_area=EXCLUDED.living_area,land_area=EXCLUDED.land_area,
 land_area_unit=EXCLUDED.land_area_unit,land_value=EXCLUDED.land_value,
 improvement_value=EXCLUDED.improvement_value,
 total_assessed_value=EXCLUDED.total_assessed_value,
 market_value=EXCLUDED.market_value,source_hash=EXCLUDED.source_hash,imported_at=NOW()
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


def parcel_id(row: dict[str, str]) -> str | None:
    local = text_value(row.get("PARCEL_ID"))
    county_number = text_value(row.get("CO_NO"))
    return f"{county_number}:{local}" if county_number and local else None


def parse_nal(row: dict[str, str]) -> tuple[Any, ...] | None:
    identity = parcel_id(row)
    county_number = text_value(row.get("CO_NO"))
    year = integer_value(row.get("ASMNT_YR"))
    if not identity or county_number not in COUNTIES or not year:
        return None
    market_value = decimal_value(row.get("JV"))
    land_value = decimal_value(row.get("LND_VAL"))
    improvement = None
    if market_value is not None and land_value is not None and market_value >= land_value:
        improvement = market_value - land_value
    address_parts = [text_value(row.get("PHY_ADDR1")), text_value(row.get("PHY_ADDR2"))]
    address = " ".join(part for part in address_parts if part) or None
    core = {
        "source_id": NAL_SOURCE_ID, "state": "FL", "county": COUNTIES[county_number],
        "source_parcel_id": identity, "snapshot_year": year,
        "street_address": address, "city": text_value(row.get("PHY_CITY")),
        "zip_code": text_value(row.get("PHY_ZIPCD")),
        "property_type": text_value(row.get("DOR_UC")),
        "land_use_code": text_value(row.get("DOR_UC")),
        "year_built": integer_value(row.get("ACT_YR_BLT")) or integer_value(row.get("EFF_YR_BLT")),
        "living_area": integer_value(row.get("TOT_LVG_AREA")),
        "land_area": decimal_value(row.get("LND_SQFOOT")), "land_area_unit": "square feet",
        "land_value": land_value, "improvement_value": improvement,
        "total_assessed_value": decimal_value(row.get("AV_NSD")) or decimal_value(row.get("AV_SD")),
        "market_value": market_value,
    }
    return tuple(core[name] for name in SNAPSHOT_COLUMNS[:-1]) + (stable_hash(core),)


def parse_sdf(row: dict[str, str]) -> tuple[Any, ...] | None:
    identity = parcel_id(row)
    county_number = text_value(row.get("CO_NO"))
    year = integer_value(row.get("SALE_YR"))
    month = integer_value(row.get("SALE_MO"))
    price = decimal_value(row.get("SALE_PRC"))
    if (not identity or county_number not in COUNTIES or not year or not month
            or price is None or price <= 0):
        return None
    try:
        sale_date = date(year, month, 1)
    except ValueError:
        return None
    transaction = text_value(row.get("SALE_ID_CD"))
    if not transaction:
        transaction = stable_hash({
            "parcel": identity, "date": sale_date, "price": price,
            "book": text_value(row.get("OR_BOOK")), "page": text_value(row.get("OR_PAGE")),
            "clerk": text_value(row.get("CLERK_NO")),
        })[:32]
    raw_qual = text_value(row.get("QUAL_CD"))
    qual = raw_qual.zfill(2) if raw_qual else ""
    arms_length = True if qual in {"01", "02", "03", "04", "05", "06"} else (
        None if qual in {"", "98", "99"} else False
    )
    conveyance = ";".join(filter(None, [
        f"qual:{qual}" if qual else None,
        f"change:{text_value(row.get('SAL_CHG_CD'))}" if text_value(row.get("SAL_CHG_CD")) else None,
        f"property:{text_value(row.get('VI_CD'))}" if text_value(row.get("VI_CD")) else None,
    ])) or None
    core = {
        "source_id": SDF_SOURCE_ID, "state": "FL", "county": COUNTIES[county_number],
        "source_parcel_id": identity, "transaction_id": transaction,
        "sale_date": sale_date, "sale_price": price,
        "conveyance_code": conveyance, "arms_length": arms_length,
    }
    return tuple(core[name] for name in SALE_COLUMNS[:-1]) + (stable_hash(core),)


def discover_files(client: httpx.Client, kind: str) -> list[dict[str, Any]]:
    folder = f"{ROLL_ROOT}/{kind}/{ROLL_VERSION}"
    endpoint = f"{SHAREPOINT}/_api/web/GetFolderByServerRelativeUrl('{folder}')/Files"
    response = client.get(endpoint, params={"$select": "Name,ServerRelativeUrl,Length,TimeLastModified", "$top": 5000},
                          headers={"Accept": "application/json;odata=verbose"})
    response.raise_for_status()
    files = response.json()["d"]["results"]
    if len(files) != 67:
        raise RuntimeError(f"Expected 67 {kind} files in {ROLL_VERSION}, found {len(files)}")
    return sorted(files, key=lambda item: int(item["Length"]))


def download_file(client: httpx.Client, item: dict[str, Any], destination: Path) -> str:
    digest = hashlib.sha256()
    url = BASE_URL + quote(item["ServerRelativeUrl"], safe="/")
    with client.stream("GET", url) as response:
        response.raise_for_status()
        with destination.open("wb") as output:
            for chunk in response.iter_bytes(1024 * 1024):
                output.write(chunk)
                digest.update(chunk)
    return digest.hexdigest()


def csv_rows(zip_path: Path) -> Iterator[dict[str, str]]:
    with zipfile.ZipFile(zip_path) as archive:
        members = [item for item in archive.infolist() if not item.is_dir() and item.filename.lower().endswith(".csv")]
        if len(members) != 1:
            raise RuntimeError(f"Expected one CSV in {zip_path.name}, found {len(members)}")
        with archive.open(members[0]) as raw:
            with io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace", newline="") as source:
                yield from csv.DictReader(source)


def completed_files(source_id: str) -> set[str]:
    with warehouse_engine.connect() as connection:
        return set(connection.execute(text("""
            SELECT file_name FROM public_import_files
            WHERE source_id=:source_id AND status='completed'
        """), {"source_id": source_id}).scalars())


def register_sources() -> None:
    with warehouse_engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO public_data_sources
              (source_id,state,source_name,source_url,access_method,coverage_notes,last_checked_at)
            VALUES
              (:nal,'FL','Florida DOR 2026 Preliminary NAL',:url,'zip_csv',
               'All 67 county real-property assessment rolls; owner and legal-description fields excluded',NOW()),
              (:sdf,'FL','Florida DOR 2026 Preliminary SDF',:url,'zip_csv',
               'All 67 county sale files; sale dates have month precision',NOW())
            ON CONFLICT(source_id) DO UPDATE SET last_checked_at=NOW(),updated_at=NOW()
        """), {"nal": NAL_SOURCE_ID, "sdf": SDF_SOURCE_ID, "url": SOURCE_PAGE})


def import_file(kind: str, item: dict[str, Any], client: httpx.Client,
                batch_size: int, dry_run: bool) -> int:
    source_id = NAL_SOURCE_ID if kind == "NAL" else SDF_SOURCE_ID
    parser = parse_nal if kind == "NAL" else parse_sdf
    sql = SNAPSHOT_SQL if kind == "NAL" else SALE_SQL
    filename = item["Name"]
    rows_seen = rows_loaded = 0
    with tempfile.NamedTemporaryFile(prefix="fl_roll_", suffix=".zip", delete=False) as temporary:
        path = Path(temporary.name)
    try:
        checksum = download_file(client, item, path)
        connection = warehouse_engine.raw_connection() if not dry_run else None
        try:
            cursor = connection.cursor() if connection else None
            batch: dict[tuple[Any, ...], tuple[Any, ...]] = {}
            for row in csv_rows(path):
                rows_seen += 1
                parsed = parser(row)
                if parsed is not None:
                    key = (parsed[3], parsed[4])
                    batch[key] = parsed
                if len(batch) >= batch_size:
                    if cursor:
                        execute_values(cursor, sql, list(batch.values()), page_size=batch_size)
                        connection.commit()
                    rows_loaded += len(batch); batch.clear()
                    print(f"{kind} {filename}: source={rows_seen:,} loaded={rows_loaded:,}")
            if batch:
                if cursor:
                    execute_values(cursor, sql, list(batch.values()), page_size=batch_size)
                    connection.commit()
                rows_loaded += len(batch)
            if connection:
                with connection.cursor() as manifest:
                    manifest.execute("""
                        INSERT INTO public_import_files
                          (source_id,file_name,file_url,file_size,sha256,row_count,status,completed_at)
                        VALUES(%s,%s,%s,%s,%s,%s,'completed',NOW())
                        ON CONFLICT(source_id,file_name) DO UPDATE SET
                          file_url=EXCLUDED.file_url,file_size=EXCLUDED.file_size,
                          sha256=EXCLUDED.sha256,row_count=EXCLUDED.row_count,
                          status='completed',completed_at=NOW()
                    """, (source_id, filename, BASE_URL + item["ServerRelativeUrl"],
                           int(item["Length"]), checksum, rows_loaded))
                connection.commit()
        finally:
            if connection:
                connection.close()
        print(f"complete {kind} {filename}: source={rows_seen:,} loaded={rows_loaded:,}")
        return rows_loaded
    finally:
        path.unlink(missing_ok=True)


def run(kind: str, county: str | None, batch_size: int, dry_run: bool) -> None:
    with httpx.Client(timeout=300, follow_redirects=True,
                      headers={"User-Agent": "nj-sheriff-sale-platform/1.0"}) as client:
        kinds = ("NAL", "SDF") if kind == "both" else (kind,)
        if not dry_run:
            register_sources()
        for current_kind in kinds:
            source_id = NAL_SOURCE_ID if current_kind == "NAL" else SDF_SOURCE_ID
            done = completed_files(source_id) if not dry_run else set()
            files = discover_files(client, current_kind)
            if county:
                files = [item for item in files if item["Name"].lower().startswith(county.lower() + " ")]
                if not files:
                    raise RuntimeError(f"No {current_kind} file found for county {county!r}")
            for number, item in enumerate(files, 1):
                if item["Name"] in done:
                    print(f"skip completed {current_kind} {item['Name']}")
                    continue
                print(f"start {current_kind} file={number}/{len(files)} name={item['Name']} size={int(item['Length']):,}")
                import_file(current_kind, item, client, batch_size, dry_run)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=("NAL", "SDF", "both"), default="both")
    parser.add_argument("--county", help="Exact county name, for a single-county run")
    parser.add_argument("--batch-size", type=int, default=5_000)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply-migration", action="store_true")
    args = parser.parse_args()
    if args.apply_migration:
        with warehouse_engine.begin() as connection:
            connection.connection.cursor().execute(MIGRATION.read_text())
    run(args.kind, args.county, args.batch_size, args.dry_run)


if __name__ == "__main__":
    main()
