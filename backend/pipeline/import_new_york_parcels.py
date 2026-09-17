"""Import the public NYS tax-parcel assessment layer without owner/mail fields.

This is a 2025 assessment snapshot, not historical building characteristics.
Outside NYC, only exact SWIS + print-key IDs are used. NYC rows use their
ten-digit BBL in SBL. No address-based guesses are made.
"""
from __future__ import annotations

import argparse
import time
from typing import Any, Iterator

import httpx
from psycopg2.extras import execute_values
from sqlalchemy import text

from app.database.session import warehouse_engine
from pipeline.import_new_york_assessment_rolls import parcel_id
from pipeline.public_property_records import decimal_value, integer_value, stable_hash, text_value

SOURCE_ID = "ny_nys_gis_tax_parcels_2025"
NYC_COUNTIES = {"Bronx", "Kings", "NewYork", "Queens", "Richmond"}
NYC_COUNTY_NAMES = {"NewYork": "New York"}
COUNTY_NAME_FIXES = {**NYC_COUNTY_NAMES, "StLawrence": "St Lawrence"}
NYC_BOROUGH_DIGITS = {"NewYork": "1", "Bronx": "2", "Kings": "3",
                      "Queens": "4", "Richmond": "5"}
SOURCE_URL = "https://gisservices.its.ny.gov/arcgis/rest/services/NYS_Tax_Parcels_Public/FeatureServer/1"
QUERY_URL = f"{SOURCE_URL}/query"
FIELDS = (
    "OBJECTID", "COUNTY_NAME", "MUNI_NAME", "SWIS", "PRINT_KEY", "SBL", "ROLL_YR",
    "LOC_ST_NBR", "LOC_STREET", "LOC_UNIT", "LOC_ZIP", "PARCEL_ADDR", "PROP_CLASS",
    "YR_BLT", "SQFT_LIVING", "NBR_BEDROOMS", "NBR_FULL_BATHS",
    "ACRES", "LAND_AV", "TOTAL_AV", "SCHOOL_CODE", "SCHOOL_NAME",
)
COLUMNS = (
    "source_id", "state", "county", "source_parcel_id", "snapshot_year",
    "street_address", "city", "zip_code", "property_type", "land_use_code",
    "year_built", "living_area", "land_area", "land_area_unit", "bedrooms",
    "bathrooms", "land_value", "improvement_value", "total_assessed_value",
    "school_district_code", "school_district_name", "source_hash",
)
SQL = f"""INSERT INTO public_property_snapshots ({','.join(COLUMNS)}) VALUES %s
ON CONFLICT(source_id,source_parcel_id,snapshot_year) DO UPDATE SET
  street_address=EXCLUDED.street_address,city=EXCLUDED.city,zip_code=EXCLUDED.zip_code,
  property_type=EXCLUDED.property_type,land_use_code=EXCLUDED.land_use_code,
  year_built=EXCLUDED.year_built,living_area=EXCLUDED.living_area,
  land_area=EXCLUDED.land_area,land_area_unit=EXCLUDED.land_area_unit,
  bedrooms=EXCLUDED.bedrooms,bathrooms=EXCLUDED.bathrooms,
  land_value=EXCLUDED.land_value,improvement_value=EXCLUDED.improvement_value,
  total_assessed_value=EXCLUDED.total_assessed_value,
  school_district_code=EXCLUDED.school_district_code,
  school_district_name=EXCLUDED.school_district_name,
  source_hash=EXCLUDED.source_hash,imported_at=NOW()
WHERE public_property_snapshots.source_hash<>EXCLUDED.source_hash"""


def positive_int(value: Any, maximum: int) -> int | None:
    number = integer_value(value)
    return number if number is not None and 0 < number <= maximum else None


def parse(attributes: dict[str, Any]) -> tuple[Any, ...] | None:
    raw_county = text_value(attributes.get("COUNTY_NAME"))
    county = COUNTY_NAME_FIXES.get(raw_county, raw_county)
    if raw_county in NYC_COUNTIES:
        sbl = text_value(attributes.get("SBL"))
        identity = (f"NYC:BBL:{sbl}" if sbl and len(sbl) == 10 and sbl.isdigit()
                    and sbl.startswith(NYC_BOROUGH_DIGITS[raw_county]) else None)
    else:
        identity = parcel_id(attributes.get("SWIS"), attributes.get("PRINT_KEY"))
    year = integer_value(attributes.get("ROLL_YR"))
    if not county or not identity or year is None or not 2020 <= year <= 2100:
        return None
    address = " ".join(filter(None, (
        text_value(attributes.get("LOC_ST_NBR")),
        text_value(attributes.get("LOC_STREET")),
        text_value(attributes.get("LOC_UNIT")),
    ))) or None
    land = decimal_value(attributes.get("LAND_AV"))
    total = decimal_value(attributes.get("TOTAL_AV"))
    improvement = total - land if total is not None and land is not None and total >= land else None
    acres = decimal_value(attributes.get("ACRES"))
    beds = decimal_value(attributes.get("NBR_BEDROOMS"))
    baths = decimal_value(attributes.get("NBR_FULL_BATHS"))
    prop_class = text_value(attributes.get("PROP_CLASS"))
    built = positive_int(attributes.get("YR_BLT"), year)
    core = {
        "source_id": SOURCE_ID, "state": "NY", "county": county,
        "source_parcel_id": identity, "snapshot_year": year,
        "street_address": address or text_value(attributes.get("PARCEL_ADDR")),
        "city": text_value(attributes.get("MUNI_NAME")),
        "zip_code": text_value(attributes.get("LOC_ZIP")),
        "property_type": prop_class, "land_use_code": prop_class,
        "year_built": built if built is not None and built >= 1600 else None,
        "living_area": positive_int(attributes.get("SQFT_LIVING"), 100000),
        "land_area": acres if acres is not None and acres > 0 else None,
        "land_area_unit": "acres" if acres is not None and acres > 0 else None,
        "bedrooms": beds if beds is not None and 0 < beds <= 100 else None,
        "bathrooms": baths if baths is not None and 0 < baths <= 100 else None,
        "land_value": land, "improvement_value": improvement,
        "total_assessed_value": total,
        "school_district_code": text_value(attributes.get("SCHOOL_CODE")),
        "school_district_name": text_value(attributes.get("SCHOOL_NAME")),
    }
    return tuple(core[column] for column in COLUMNS[:-1]) + (stable_hash(core),)


def pages(client: httpx.Client, county: str, page_size: int = 2000) -> Iterator[tuple[int, list[dict[str, Any]]]]:
    if not county or "'" in county:
        raise ValueError("Invalid county")
    offset = 0
    while True:
        params = {
            "f": "json", "where": f"COUNTY_NAME='{county}'", "outFields": ",".join(FIELDS),
            "returnGeometry": "false", "orderByFields": "OBJECTID",
            "resultOffset": offset, "resultRecordCount": page_size,
        }
        for attempt in range(5):
            try:
                response = client.get(QUERY_URL, params=params)
                response.raise_for_status()
                payload = response.json()
                if "error" in payload:
                    raise ValueError(f"ArcGIS error: {payload['error']}")
                records = [feature["attributes"] for feature in payload.get("features", [])]
                break
            except (httpx.HTTPError, ValueError, KeyError):
                if attempt == 4:
                    raise
                time.sleep(2 ** attempt)
        if not records:
            return
        yield offset, records
        offset += len(records)
        if len(records) < page_size and not payload.get("exceededTransferLimit"):
            return


def public_counties(client: httpx.Client) -> list[str]:
    response = client.get(QUERY_URL, params={
        "f": "json", "where": "1=1", "outFields": "COUNTY_NAME",
        "returnGeometry": "false", "returnDistinctValues": "true",
        "orderByFields": "COUNTY_NAME", "resultRecordCount": 100,
    })
    response.raise_for_status()
    payload = response.json()
    if "error" in payload or payload.get("exceededTransferLimit"):
        raise ValueError(f"Could not enumerate public counties: {payload.get('error') or 'incomplete result'}")
    return sorted({name for feature in payload.get("features", [])
                   if (name := text_value(feature["attributes"].get("COUNTY_NAME")))})


def import_county(county: str, dry_run: bool = False, page_size: int = 2000) -> dict[str, int]:
    stats = {"seen": 0, "parsed": 0, "with_bedrooms": 0, "with_bathrooms": 0,
             "with_living_area": 0, "with_year_built": 0}
    raw = warehouse_engine.raw_connection() if not dry_run else None
    try:
        with httpx.Client(timeout=120, follow_redirects=True) as client:
            for offset, source_rows in pages(client, county, page_size):
                batch = {}
                for source in source_rows:
                    stats["seen"] += 1
                    row = parse(source)
                    if row is None:
                        continue
                    batch[(row[3], row[4])] = row
                for row in batch.values():
                    stats["parsed"] += 1
                    for name in ("bedrooms", "bathrooms", "living_area", "year_built"):
                        stats[f"with_{name}"] += row[COLUMNS.index(name)] is not None
                if raw is not None and batch:
                    cursor = raw.cursor()
                    execute_values(cursor, SQL, list(batch.values()), page_size=1000)
                    raw.commit()
                print(f"{county}: offset={offset + len(source_rows):,} parsed={stats['parsed']:,}", flush=True)
    finally:
        if raw is not None:
            raw.close()
    return stats


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--counties", nargs="+", default=["Albany"])
    parser.add_argument("--all-public-counties", action="store_true",
                        help="Import every county currently shared by the state layer")
    parser.add_argument("--skip-counties", nargs="*", default=[],
                        help="Skip already-imported counties during an all-public-counties run")
    parser.add_argument("--page-size", type=int, default=2000)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.page_size <= 5000:
        parser.error("--page-size must be between 1 and 5000")
    if args.all_public_counties:
        with httpx.Client(timeout=120, follow_redirects=True) as client:
            args.counties = public_counties(client)
        print(f"Public counties ({len(args.counties)}): {', '.join(args.counties)}", flush=True)
    args.counties = [county for county in args.counties if county not in args.skip_counties]
    if not args.dry_run:
        with warehouse_engine.begin() as connection:
            connection.execute(text("""INSERT INTO public_data_sources
              (source_id,state,source_name,source_url,access_method,coverage_notes,last_checked_at)
              VALUES(:id,'NY','NYS public tax parcels, 2025 assessment',:url,'ArcGIS public FeatureServer',
              '2025 assessment only; county permission varies. Bedroom/bath fields may be blank; bathrooms are full baths. Owner and mailing fields excluded.',NOW())
              ON CONFLICT(source_id) DO UPDATE SET last_checked_at=NOW(),updated_at=NOW()"""),
              {"id": SOURCE_ID, "url": SOURCE_URL})
    for county in args.counties:
        print(f"{county}: {import_county(county, args.dry_run, args.page_size)}", flush=True)


if __name__ == "__main__":
    main()
