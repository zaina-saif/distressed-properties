"""Import non-personal NYS ORPTS local assessment-roll fields.

The official dataset contains 2021-2025 final rolls for all New York cities and
towns except New York City. Owner, mailing, exemption, deed-book, and deed-page
columns are deliberately neither requested nor stored.
"""
from __future__ import annotations

import argparse
import time
from decimal import Decimal
from typing import Any, Iterator

import httpx
from psycopg2.extras import execute_values
from sqlalchemy import text

from app.database.session import warehouse_engine
from pipeline.public_property_records import decimal_value, integer_value, stable_hash, text_value

SOURCE_ID = "ny_orpts_local_assessment_rolls_2021_2025"
SOURCE_PAGE = "https://data.ny.gov/d/7vem-aaz7"
API_URL = "https://data.ny.gov/resource/7vem-aaz7.json"
FIELDS = (
    "roll_year", "county_name", "municipality_name", "swis_code", "print_key_code",
    "property_class", "property_class_description", "parcel_address_number",
    "parcel_address_street", "parcel_address_suff", "full_market_value",
    "assessment_land", "assessment_total", "school_district_code", "school_district_name",
)
COLUMNS = (
    "source_id", "state", "county", "source_parcel_id", "snapshot_year",
    "street_address", "city", "property_type", "land_use_code", "land_value",
    "improvement_value", "total_assessed_value", "school_district_code",
    "school_district_name", "source_hash",
)
SQL = f"""INSERT INTO public_property_snapshots ({','.join(COLUMNS)}) VALUES %s
ON CONFLICT(source_id,source_parcel_id,snapshot_year) DO UPDATE SET
 street_address=EXCLUDED.street_address,city=EXCLUDED.city,property_type=EXCLUDED.property_type,
 land_use_code=EXCLUDED.land_use_code,land_value=EXCLUDED.land_value,
 improvement_value=EXCLUDED.improvement_value,total_assessed_value=EXCLUDED.total_assessed_value,
 school_district_code=EXCLUDED.school_district_code,school_district_name=EXCLUDED.school_district_name,
 source_hash=EXCLUDED.source_hash,imported_at=NOW()
WHERE public_property_snapshots.source_hash<>EXCLUDED.source_hash"""


def parcel_id(swis: Any, print_key: Any) -> str | None:
    swis = text_value(swis)
    print_key = text_value(print_key)
    if not swis or not print_key:
        return None
    normalized = "".join(c for c in print_key.upper() if c.isalnum())
    return f"NY:{swis}:{normalized}" if normalized else None


def parse(row: dict[str, Any]) -> tuple[Any, ...] | None:
    identity = parcel_id(row.get("swis_code"), row.get("print_key_code"))
    year = integer_value(row.get("roll_year"))
    county = text_value(row.get("county_name"))
    if not identity or not year or not county:
        return None
    address = " ".join(filter(None, (
        text_value(row.get("parcel_address_number")),
        text_value(row.get("parcel_address_street")),
        text_value(row.get("parcel_address_suff")),
    ))) or None
    land = decimal_value(row.get("assessment_land"))
    total = decimal_value(row.get("assessment_total"))
    improvement = total - land if total is not None and land is not None and total >= land else None
    prop_code = text_value(row.get("property_class"))
    core = {
        "source_id": SOURCE_ID, "state": "NY", "county": county,
        "source_parcel_id": identity, "snapshot_year": year, "street_address": address,
        "city": text_value(row.get("municipality_name")),
        "property_type": text_value(row.get("property_class_description")),
        "land_use_code": prop_code, "land_value": land,
        "improvement_value": improvement, "total_assessed_value": total,
        "school_district_code": text_value(row.get("school_district_code")),
        "school_district_name": text_value(row.get("school_district_name")),
    }
    return tuple(core[name] for name in COLUMNS[:-1]) + (stable_hash(core),)


def pages(client: httpx.Client, year: int, page_size: int, start_offset: int = 0) -> Iterator[tuple[int, list[dict[str, Any]]]]:
    offset = start_offset
    while True:
        params = {"$select": ",".join(FIELDS), "$where": f"roll_year={year}",
                  "$order": ":id", "$limit": page_size, "$offset": offset}
        for attempt in range(6):
            try:
                response = client.get(API_URL, params=params)
                response.raise_for_status()
                rows = response.json()
                break
            except (httpx.HTTPError, ValueError):
                if attempt == 5:
                    raise
                time.sleep(2 ** attempt)
        if not rows:
            break
        yield offset, rows
        offset += len(rows)
        if len(rows) < page_size:
            break


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", nargs="+", type=int, default=[2025, 2024, 2023, 2022, 2021])
    parser.add_argument("--page-size", type=int, default=50000)
    parser.add_argument("--start-offset", type=int, default=0,
                        help="Resume offset; use only when importing a single year")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.start_offset and len(args.years) != 1:
        parser.error("--start-offset requires exactly one --years value")
    if not args.dry_run:
        with warehouse_engine.begin() as connection:
            connection.execute(text("""INSERT INTO public_data_sources
              (source_id,state,source_name,source_url,access_method,coverage_notes,last_checked_at)
              VALUES(:id,'NY','NYS ORPTS Property Assessment Data from Local Assessment Rolls',:url,
              'Socrata API','2021-2025 final rolls for all cities/towns outside NYC; owner, mailing, exemption and deed fields excluded',NOW())
              ON CONFLICT(source_id) DO UPDATE SET last_checked_at=NOW(),updated_at=NOW()"""),
                               {"id": SOURCE_ID, "url": SOURCE_PAGE})
    raw = warehouse_engine.raw_connection() if not args.dry_run else None
    total_loaded = 0
    try:
        with httpx.Client(timeout=180, follow_redirects=True) as client:
            for year in args.years:
                year_loaded = 0
                for offset, source_rows in pages(client, year, args.page_size, args.start_offset):
                    rows_by_key = {}
                    for source in source_rows:
                        row = parse(source)
                        if row:
                            rows_by_key[row[3]] = row
                    if raw is not None and rows_by_key:
                        cursor = raw.cursor()
                        execute_values(cursor, SQL, list(rows_by_key.values()), page_size=10000)
                        raw.commit()
                    year_loaded += len(rows_by_key)
                    total_loaded += len(rows_by_key)
                    print(f"NY roll {year}: offset={offset + len(source_rows):,} loaded={year_loaded:,}", flush=True)
                args.start_offset = 0
    finally:
        if raw is not None:
            raw.close()
    print(f"complete dry_run={args.dry_run} NY assessment snapshots={total_loaded:,}")


if __name__ == "__main__":
    main()
