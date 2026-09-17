"""Fill blank MD street addresses from public SDAT premise components.

Only situs fields are requested. Existing nonblank warehouse addresses are never
overwritten, and zero-filled house numbers are explicitly marked unavailable.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import time
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
from psycopg2.extras import execute_values
from sqlalchemy import text

from app.database.session import warehouse_engine
from pipeline.import_maryland_property_data import FIELDS, SOURCE_URL, address_parts
from pipeline.public_property_records import text_value

ARCGIS_URL = "https://mdgeodata.md.gov/imap/rest/services/PlanningCadastre/MD_ParcelBoundaries/MapServer/0/query"
ARCGIS_FIELDS = "OBJECTID,ACCTID,ADDRESS,CITY,ZIPCODE,PREMSNUM,PREMSDIR,PREMSNAM,PREMSTYP,PREMCITY,PREMZIP"

SELECT_FIELDS = (
    FIELDS["county"], FIELDS["parcel"], FIELDS["address"], FIELDS["city"], FIELDS["zip"],
    FIELDS["premise_number"], FIELDS["premise_suffix"], FIELDS["premise_direction"],
    FIELDS["premise_name"], FIELDS["premise_type"], FIELDS["premise_city"], FIELDS["premise_zip"],
)
CSV_LABELS = {
    FIELDS["county"]: "County Name (MDP Field: CNTYNAME)",
    FIELDS["parcel"]: "Account ID (MDP Field: ACCTID)",
    FIELDS["address"]: "MDP Street Address (MDP Field: ADDRESS)",
    FIELDS["city"]: "MDP Street Address City (MDP Field: CITY)",
    FIELDS["zip"]: "MDP Street Address Zip Code (MDP Field: ZIPCODE)",
    FIELDS["premise_number"]: "PREMISE ADDRESS: Number (MDP Field: PREMSNUM. SDAT Field #20)",
    FIELDS["premise_suffix"]: "PREMISE ADDRESS: Number Suffix (SDAT Field #21)",
    FIELDS["premise_direction"]: "PREMISE ADDRESS: Direction (MDP Field: PREMSDIR. SDAT Field #22)",
    FIELDS["premise_name"]: "PREMISE ADDRESS: Name (MDP Field: PREMSNAM. SDAT Field #23)",
    FIELDS["premise_type"]: "PREMISE ADDRESS: Type (MDP Field: PREMSTYP. SDAT Field #24)",
    FIELDS["premise_city"]: "PREMISE ADDRESS: City (MDP Field: PREMCITY. SDAT Field #25)",
    FIELDS["premise_zip"]: "PREMISE ADDRESS: Zip Code (MDP Field: PREMZIP. SDAT Field #26)",
}


def canonical_header(name: str) -> str:
    return next((api for api, label in CSV_LABELS.items() if name in (api, label)), name)
WHERE = (f"({FIELDS['address']} IS NULL OR {FIELDS['address']} = '') "
         f"AND {FIELDS['premise_name']} IS NOT NULL")
UPDATE_SQL = """UPDATE public_property_snapshots AS p SET
    street_address=v.street_address,
    city=COALESCE(p.city,v.city),
    zip_code=COALESCE(p.zip_code,v.zip_code),
    house_number_unavailable=v.house_number_unavailable,
    imported_at=NOW()
FROM (VALUES %s) AS v(county,source_parcel_id,street_address,city,zip_code,house_number_unavailable)
WHERE p.source_id='md_sdat_mdp_statewide' AND p.state='MD' AND p.snapshot_year=2026
  AND p.county=v.county AND p.source_parcel_id=v.source_parcel_id
  AND (p.street_address IS NULL OR BTRIM(p.street_address)='')"""
ARCGIS_UPDATE_SQL = """UPDATE public_property_snapshots AS p SET
    street_address=v.street_address,
    city=COALESCE(p.city,v.city),
    zip_code=COALESCE(p.zip_code,v.zip_code),
    house_number_unavailable=v.house_number_unavailable,
    imported_at=NOW()
FROM (VALUES %s) AS v(source_parcel_id,street_address,city,zip_code,house_number_unavailable)
WHERE p.source_id='md_sdat_mdp_statewide' AND p.state='MD' AND p.snapshot_year=2026
  AND p.source_parcel_id=v.source_parcel_id
  AND (p.street_address IS NULL OR BTRIM(p.street_address)='')"""
ARCGIS_PARTIAL_SQL = """UPDATE public_property_snapshots AS p SET
    street_address=COALESCE(NULLIF(BTRIM(p.street_address),''),v.street_address),
    city=COALESCE(p.city,v.city),
    zip_code=COALESCE(p.zip_code,v.zip_code),
    house_number_unavailable=CASE WHEN v.street_address IS NOT NULL
      THEN v.house_number_unavailable ELSE p.house_number_unavailable END,
    imported_at=NOW()
FROM (VALUES %s) AS v(source_parcel_id,street_address,city,zip_code,house_number_unavailable)
WHERE p.source_id='md_sdat_mdp_statewide' AND p.state='MD' AND p.snapshot_year=2026
  AND p.source_parcel_id=v.source_parcel_id
  AND (p.street_address IS NULL OR BTRIM(p.street_address)='')
  AND (v.street_address IS NOT NULL OR (p.city IS NULL AND v.city IS NOT NULL)
       OR (p.zip_code IS NULL AND v.zip_code IS NOT NULL))"""


async def pages(client: httpx.AsyncClient, page_size: int, start_offset: int = 0,
                county: str | None = None) -> AsyncIterator[tuple[int, list[dict[str, Any]]]]:
    offset = start_offset
    where = WHERE
    if county:
        where += f" AND {FIELDS['county']}='{county.replace(chr(39), chr(39) * 2)}'"
    while True:
        response = await client.get(SOURCE_URL, params={
            "$select": ",".join(SELECT_FIELDS), "$where": where,
            "$order": f"{FIELDS['county']},{FIELDS['parcel']}",
            "$limit": page_size, "$offset": offset,
        })
        response.raise_for_status()
        rows = response.json()
        if not rows:
            return
        yield offset, rows
        offset += len(rows)
        if len(rows) < page_size:
            return


def parse(row: dict[str, Any]) -> tuple[str, str, str, str | None, str | None, bool] | None:
    county = text_value(row.get(FIELDS["county"]))
    parcel = text_value(row.get(FIELDS["parcel"]))
    address, city, zip_code, missing_number = address_parts(row)
    return (county, parcel, address, city, zip_code, missing_number) if county and parcel and address else None


def apply_rows(rows: list[dict[str, Any]], raw: Any | None) -> int:
    batch = {key: record for row in rows
             if (record := parse(row)) is not None
             for key in [(record[0], record[1])]}
    if raw is not None and batch:
        cursor = raw.cursor()
        execute_values(cursor, UPDATE_SQL, list(batch.values()), page_size=1000)
        raw.commit()
    return len(batch)


async def run(page_size: int, start_offset: int, county: str | None, dry_run: bool) -> None:
    seen = prepared = 0
    raw = warehouse_engine.raw_connection() if not dry_run else None
    try:
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            async for offset, source_rows in pages(client, page_size, start_offset, county):
                seen += len(source_rows)
                prepared += apply_rows(source_rows, raw)
                print(f"offset={offset + len(source_rows):,} source_rows={seen:,} usable={prepared:,}", flush=True)
    finally:
        if raw is not None:
            raw.close()
    print(f"complete county={county or 'all'} source_rows={seen:,} usable={prepared:,} dry_run={dry_run}")


def run_file(path: Path, page_size: int, dry_run: bool) -> None:
    seen = prepared = 0
    raw = warehouse_engine.raw_connection() if not dry_run else None
    try:
        with path.open(encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            header_map = {name: canonical_header(name) for name in (reader.fieldnames or [])}
            required = {FIELDS["county"], FIELDS["parcel"], FIELDS["premise_name"]}
            if not required.issubset(header_map.values()):
                raise ValueError(f"CSV must include official columns: {', '.join(sorted(required))}")
            batch = []
            for row in reader:
                batch.append({header_map[name]: value for name, value in row.items() if name is not None})
                if len(batch) >= page_size:
                    prepared += apply_rows(batch, raw)
                    seen += len(batch)
                    print(f"CSV rows={seen:,} usable={prepared:,}", flush=True)
                    batch.clear()
            if batch:
                prepared += apply_rows(batch, raw)
                seen += len(batch)
    finally:
        if raw is not None:
            raw.close()
    print(f"complete file={path} source_rows={seen:,} usable={prepared:,} dry_run={dry_run}")


def arcgis_record(attributes: dict[str, Any]) -> tuple[str, str, str | None, str | None, bool] | None:
    record = arcgis_location_record(attributes)
    return record if record and record[1] else None


def arcgis_location_record(attributes: dict[str, Any]) -> tuple[str, str | None, str | None, str | None, bool] | None:
    row = {
        FIELDS["address"]: attributes.get("ADDRESS"),
        FIELDS["city"]: attributes.get("CITY"),
        FIELDS["zip"]: attributes.get("ZIPCODE"),
        FIELDS["premise_number"]: attributes.get("PREMSNUM"),
        FIELDS["premise_direction"]: attributes.get("PREMSDIR"),
        FIELDS["premise_name"]: attributes.get("PREMSNAM"),
        FIELDS["premise_type"]: attributes.get("PREMSTYP"),
        FIELDS["premise_city"]: attributes.get("PREMCITY"),
        FIELDS["premise_zip"]: attributes.get("PREMZIP"),
    }
    parcel = text_value(attributes.get("ACCTID"))
    address, city, zip_code, missing_number = address_parts(row)
    return (parcel, address, city, zip_code, missing_number) if parcel and (address or city or zip_code) else None


def run_arcgis(page_size: int, after_objectid: int, dry_run: bool) -> None:
    """Read official parcel-boundary premise fields without owner/mailing data."""
    if page_size > 1000:
        raise ValueError("Maryland parcel-boundary service limits pages to 1000")
    seen = prepared = 0
    raw = warehouse_engine.raw_connection() if not dry_run else None
    try:
        with httpx.Client(timeout=120, follow_redirects=True) as client:
            while True:
                for attempt in range(5):
                    try:
                        response = client.get(ARCGIS_URL, params={
                            "where": f"ADDRESS IS NULL AND PREMSNAM IS NOT NULL AND OBJECTID>{after_objectid}",
                            "outFields": ARCGIS_FIELDS, "returnGeometry": "false",
                            "orderByFields": "OBJECTID", "resultRecordCount": page_size, "f": "json",
                        })
                        response.raise_for_status()
                        payload = response.json()
                        if "error" in payload:
                            raise ValueError(str(payload["error"]))
                        rows = [feature["attributes"] for feature in payload.get("features", [])]
                        break
                    except (httpx.HTTPError, ValueError, KeyError):
                        if attempt == 4:
                            raise
                        time.sleep(2 ** attempt)
                if not rows:
                    break
                last = int(rows[-1]["OBJECTID"])
                if last <= after_objectid:
                    raise ValueError("Maryland parcel service did not advance OBJECTID")
                batch = {record[0]: record for item in rows
                         if (record := arcgis_record(item)) is not None}
                if raw is not None and batch:
                    execute_values(raw.cursor(), ARCGIS_UPDATE_SQL, list(batch.values()), page_size=1000)
                    raw.commit()
                seen += len(rows)
                prepared += len(batch)
                after_objectid = last
                print(f"after_objectid={last} source_rows={seen:,} usable={prepared:,}", flush=True)
                if len(rows) < page_size and not payload.get("exceededTransferLimit"):
                    break
    finally:
        if raw is not None:
            raw.close()
    print(f"complete ArcGIS source_rows={seen:,} usable={prepared:,} dry_run={dry_run}")


def run_arcgis_missing(page_size: int, after_parcel: str, county: str | None, dry_run: bool) -> None:
    """Look up remaining blank 2026 warehouse IDs, including GIS combined addresses."""
    if page_size > 100:
        raise ValueError("Use at most 100 parcel IDs per Maryland GIS request")
    checked = matched = 0
    raw = warehouse_engine.raw_connection() if not dry_run else None
    try:
        with httpx.Client(timeout=120, follow_redirects=True) as client:
            while True:
                with warehouse_engine.connect() as connection:
                    ids = connection.execute(text("""SELECT source_parcel_id
                      FROM public_property_snapshots
                      WHERE source_id='md_sdat_mdp_statewide' AND state='MD'
                        AND snapshot_year=2026 AND (:county IS NULL OR county=:county)
                        AND (street_address IS NULL OR BTRIM(street_address)='')
                        AND source_parcel_id>:after
                      ORDER BY source_parcel_id LIMIT :limit"""),
                      {"county": county, "after": after_parcel, "limit": page_size}).scalars().all()
                if not ids:
                    break
                safe_ids = ",".join("'" + parcel.replace("'", "''") + "'" for parcel in ids)
                for attempt in range(5):
                    try:
                        response = client.get(ARCGIS_URL, params={
                            "where": f"ACCTID IN ({safe_ids})", "outFields": ARCGIS_FIELDS,
                            "returnGeometry": "false", "f": "json",
                        })
                        response.raise_for_status()
                        payload = response.json()
                        if "error" in payload:
                            raise ValueError(str(payload["error"]))
                        rows = [feature["attributes"] for feature in payload.get("features", [])]
                        break
                    except (httpx.HTTPError, ValueError, KeyError):
                        if attempt == 4:
                            raise
                        time.sleep(2 ** attempt)
                batch = {record[0]: record for item in rows
                         if (record := arcgis_location_record(item)) is not None and record[0] in ids}
                if raw is not None and batch:
                    execute_values(raw.cursor(), ARCGIS_PARTIAL_SQL, list(batch.values()), page_size=100)
                    raw.commit()
                checked += len(ids)
                matched += len(batch)
                after_parcel = ids[-1]
                print(f"after_parcel={after_parcel} checked={checked:,} usable={matched:,}", flush=True)
    finally:
        if raw is not None:
            raw.close()
    print(f"complete GIS missing lookup checked={checked:,} usable={matched:,} dry_run={dry_run}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--county", help="Optional exact county name")
    parser.add_argument("--file", type=Path, help="Official Maryland assessment CSV export")
    parser.add_argument("--page-size", type=int, default=5000)
    parser.add_argument("--start-offset", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--arcgis", action="store_true",
                        help="Use official Maryland parcel-boundary premise fields")
    parser.add_argument("--arcgis-missing", action="store_true",
                        help="Look up remaining blank 2026 parcel IDs in official GIS")
    parser.add_argument("--after-objectid", type=int, default=0,
                        help="Resume ArcGIS after the last printed committed OBJECTID")
    parser.add_argument("--after-parcel", default="",
                        help="Resume ArcGIS missing-ID lookup after last printed parcel ID")
    args = parser.parse_args()
    if not 1 <= args.page_size <= 50000:
        parser.error("--page-size must be between 1 and 50000")
    if args.arcgis_missing:
        run_arcgis_missing(min(args.page_size, 100), args.after_parcel, args.county, args.dry_run)
    elif args.arcgis:
        run_arcgis(min(args.page_size, 1000), args.after_objectid, args.dry_run)
    elif args.file:
        run_file(args.file, args.page_size, args.dry_run)
    else:
        asyncio.run(run(args.page_size, args.start_offset, args.county, args.dry_run))


if __name__ == "__main__":
    main()
