"""Load any New Jersey county MOD-IV file into the canonical parcel tables."""
from __future__ import annotations

import argparse
import csv
import io
import re
from dataclasses import asdict
from pathlib import Path

from pipeline.nj_property_records import parse_modiv
from pipeline.parcel_identity import normalize_text, pams_pin

BACKEND = Path(__file__).resolve().parents[1]
RAW_MODIV = BACKEND / "data" / "nj_property" / "raw" / "modiv"
MIGRATION = BACKEND / "migrations" / "013_canonical_parcel_identity.sql"

NJ_COUNTIES = {
    "01": "Atlantic", "02": "Bergen", "03": "Burlington", "04": "Camden",
    "05": "Cape May", "06": "Cumberland", "07": "Essex", "08": "Gloucester",
    "09": "Hudson", "10": "Hunterdon", "11": "Mercer", "12": "Middlesex",
    "13": "Monmouth", "14": "Morris", "15": "Ocean", "16": "Passaic",
    "17": "Salem", "18": "Somerset", "19": "Sussex", "20": "Union",
    "21": "Warren",
}
COUNTY_CODES = {name.casefold(): code for code, name in NJ_COUNTIES.items()}


def filename_key(value: str) -> str:
    return re.sub(r"[^a-z]", "", value.casefold())


def resolve_county(value: str) -> tuple[str, str]:
    cleaned = value.strip()
    if cleaned.zfill(2) in NJ_COUNTIES:
        code = cleaned.zfill(2)
        return code, NJ_COUNTIES[code]
    code = COUNTY_CODES.get(cleaned.casefold())
    if code is None:
        raise ValueError(f"Unknown NJ county: {value}")
    return code, NJ_COUNTIES[code]


def find_modiv_file(county: str, year: int) -> Path:
    _, county_name = resolve_county(county)
    directory = RAW_MODIV / str(year)
    if not directory.exists():
        raise FileNotFoundError(f"MOD-IV year directory not found: {directory}")
    prefix = filename_key(county_name)
    matches = [path for path in directory.iterdir()
               if path.is_file() and filename_key(path.stem).startswith(prefix)]
    if len(matches) != 1:
        raise FileNotFoundError(
            f"Expected one {county_name} MOD-IV file for {year}; found {len(matches)}"
        )
    return matches[0]


STAGE_COLUMNS = [
    "county", "source_year", "municipality_code", "block", "lot", "qualifier",
    "pams_pin", "property_location", "normalized_address", "property_class",
    "building_description", "land_description", "acreage", "zoning", "building_class",
    "year_built", "land_assessed", "improvement_assessed", "total_assessed",
    "annual_property_tax", "census_tract", "census_block", "property_use_code",
    "source_file", "source_line_number", "source_hash",
]


def load_snapshot(county: str, year: int, batch_size: int = 10_000) -> int:
    from app.database.session import engine

    county_code, county_name = resolve_county(county)
    path = find_modiv_file(county_name, year)
    processed = 0
    batch: list[dict] = []
    connection = engine.raw_connection()
    try:
        _create_stage(connection)
        with path.open(encoding="latin-1") as handle:
            for line_number, line in enumerate(handle, 1):
                row = asdict(parse_modiv(line, year, str(path), line_number))
                if not row["municipality_code"].startswith(county_code):
                    continue
                row.update(
                    county=county_name,
                    pams_pin=pams_pin(row["municipality_code"], row["block"], row["lot"], row["qualifier"]),
                    normalized_address=normalize_text(row["property_location"]),
                )
                batch.append(row)
                if len(batch) >= batch_size:
                    _save_batch(connection,batch); processed += len(batch); batch.clear()
        if batch:
            _save_batch(connection,batch); processed += len(batch)
    finally:
        connection.close()
    return processed


def _create_stage(connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute("""CREATE TEMP TABLE IF NOT EXISTS canonical_modiv_import(
          county TEXT,source_year SMALLINT,municipality_code TEXT,block TEXT,lot TEXT,
          qualifier TEXT,pams_pin TEXT,property_location TEXT,normalized_address TEXT,
          property_class TEXT,building_description TEXT,land_description TEXT,acreage NUMERIC,
          zoning TEXT,building_class TEXT,year_built SMALLINT,land_assessed NUMERIC,
          improvement_assessed NUMERIC,total_assessed NUMERIC,annual_property_tax NUMERIC,
          census_tract TEXT,census_block TEXT,property_use_code TEXT,source_file TEXT,
          source_line_number INTEGER,source_hash CHAR(64)) ON COMMIT PRESERVE ROWS""")
    connection.commit()


def _save_batch(connection, batch: list[dict]) -> None:
    stream = io.StringIO()
    writer = csv.writer(stream, lineterminator="\n")
    for row in batch:
        writer.writerow(["\\N" if row.get(name) is None else row.get(name) for name in STAGE_COLUMNS])
    stream.seek(0)
    columns = ",".join(STAGE_COLUMNS)
    with connection.cursor() as cursor:
        cursor.execute("TRUNCATE canonical_modiv_import")
        cursor.copy_expert(
            f"COPY canonical_modiv_import({columns}) FROM STDIN WITH(FORMAT CSV,NULL '\\N')",
            stream,
        )
        cursor.execute("""INSERT INTO jurisdictions(state,county,municipality_code)
          SELECT DISTINCT 'NJ',county,municipality_code FROM canonical_modiv_import
          ON CONFLICT(state,municipality_code) DO UPDATE SET county=EXCLUDED.county""")
        cursor.execute("""INSERT INTO parcels(state,county,jurisdiction_id,municipality_code,
          block,lot,qualifier,pams_pin,current_address,normalized_address,first_seen_year,last_seen_year)
          SELECT DISTINCT ON (i.municipality_code,i.block,i.lot,i.qualifier)
            'NJ',i.county,j.id,i.municipality_code,i.block,i.lot,i.qualifier,i.pams_pin,
            i.property_location,i.normalized_address,i.source_year,i.source_year
          FROM canonical_modiv_import i JOIN jurisdictions j ON j.state='NJ'
            AND j.municipality_code=i.municipality_code
          ORDER BY i.municipality_code,i.block,i.lot,i.qualifier,i.source_line_number DESC
          ON CONFLICT(state,municipality_code,block,lot,qualifier) DO UPDATE SET
            county=EXCLUDED.county,jurisdiction_id=EXCLUDED.jurisdiction_id,
            current_address=EXCLUDED.current_address,normalized_address=EXCLUDED.normalized_address,
            first_seen_year=LEAST(parcels.first_seen_year,EXCLUDED.first_seen_year),
            last_seen_year=GREATEST(parcels.last_seen_year,EXCLUDED.last_seen_year),updated_at=NOW()""")
        cursor.execute("""INSERT INTO parcel_snapshots(parcel_id,source_year,property_class,
          property_location,building_description,land_description,acreage,zoning,building_class,
          year_built,land_assessed,improvement_assessed,total_assessed,annual_property_tax,
          census_tract,census_block,property_use_code,source_file,source_line_number,source_hash)
          SELECT p.id,i.source_year,i.property_class,i.property_location,i.building_description,
            i.land_description,i.acreage,i.zoning,i.building_class,i.year_built,i.land_assessed,
            i.improvement_assessed,i.total_assessed,i.annual_property_tax,i.census_tract,
            i.census_block,i.property_use_code,i.source_file,i.source_line_number,i.source_hash
          FROM canonical_modiv_import i JOIN parcels p ON p.state='NJ'
            AND p.municipality_code=i.municipality_code AND p.block=i.block
            AND p.lot=i.lot AND p.qualifier=i.qualifier
          ON CONFLICT(parcel_id,source_year,source_hash) DO NOTHING""")
    connection.commit()


def apply_migration() -> None:
    from app.database.session import engine

    connection = engine.raw_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(MIGRATION.read_text())
        connection.commit()
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply-migration", action="store_true")
    parser.add_argument("--load", action="store_true")
    parser.add_argument("--county", required=True)
    parser.add_argument("--year", required=True, type=int)
    args = parser.parse_args()
    county_code, county_name = resolve_county(args.county)
    path = find_modiv_file(county_name, args.year)
    print(f"County: {county_name} ({county_code}); source: {path}")
    if args.apply_migration:
        apply_migration(); print("Migration 013 applied")
    if args.load:
        print(f"Parcel snapshot records processed: {load_snapshot(county_name,args.year)}")


if __name__ == "__main__":
    main()
