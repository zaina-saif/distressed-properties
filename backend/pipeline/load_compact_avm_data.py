"""Build and load the compact Monmouth AVM training dataset."""
from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

from app.database.session import engine
from pipeline.load_nj_property_history import MODIV_FILES, SR1A_FILES, _copy_rows
from pipeline.nj_property_records import parse_modiv, parse_sr1a

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "migrations" / "007_compact_avm_training_data.sql"
COLUMNS = [
    "sale_year", "snapshot_year", "municipality_code", "block", "lot", "qualifier",
    "property_location", "deed_date", "recorded_date", "sale_price", "reported_price",
    "verified_price", "property_class", "qualification_codes", "building_description",
    "land_description", "acreage", "zoning", "building_class", "year_built", "living_space",
    "land_assessed", "improvement_assessed", "total_assessed", "annual_property_tax",
    "census_tract", "census_block", "property_use_code", "match_method", "source_hash",
]

def apply_migration(connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute(MIGRATION.read_text())
    connection.commit()

def snapshot_year(sale_year: int) -> int:
    return min(MODIV_FILES, key=lambda year: (abs(year - sale_year), year))

def load_snapshot(path: Path, year: int):
    candidates = defaultdict(list)
    with path.open(encoding="latin-1") as handle:
        for line_number, line in enumerate(handle, 1):
            row = parse_modiv(line, year, str(path), line_number)
            if row.property_class.strip() == "2":
                candidates[(row.municipality_code, row.block, row.lot)].append(row)
    return candidates

def training_rows(years: set[int] | None = None):
    active_year = None
    parcels = None
    for sale_year, path in SR1A_FILES.items():
        if years and sale_year not in years:
            continue
        modiv_year = snapshot_year(sale_year)
        if modiv_year != active_year:
            parcels = load_snapshot(MODIV_FILES[modiv_year], modiv_year)
            active_year = modiv_year
        with path.open(encoding="latin-1") as handle:
            for line_number, line in enumerate(handle, 1):
                sale = parse_sr1a(line, sale_year, str(path), line_number)
                if sale.county_code != "13" or sale.property_class.strip() != "2":
                    continue
                if sale.qualification_codes.strip():
                    continue
                price = sale.verified_price or sale.reported_price
                if price is None or price < 10_000:
                    continue
                matches = parcels.get((sale.municipality_code, sale.block, sale.lot), [])
                if len(matches) != 1:
                    continue
                parcel = matches[0]
                yield {
                    "sale_year": sale_year, "snapshot_year": modiv_year,
                    "municipality_code": sale.municipality_code, "block": sale.block,
                    "lot": sale.lot, "qualifier": parcel.qualifier,
                    "property_location": sale.property_location or parcel.property_location,
                    "deed_date": sale.deed_date, "recorded_date": sale.recorded_date,
                    "sale_price": price, "reported_price": sale.reported_price,
                    "verified_price": sale.verified_price, "property_class": sale.property_class,
                    "qualification_codes": sale.qualification_codes,
                    "building_description": parcel.building_description,
                    "land_description": parcel.land_description, "acreage": parcel.acreage,
                    "zoning": parcel.zoning, "building_class": parcel.building_class,
                    "year_built": sale.year_built or parcel.year_built,
                    "living_space": sale.living_space, "land_assessed": parcel.land_assessed,
                    "improvement_assessed": parcel.improvement_assessed,
                    "total_assessed": parcel.total_assessed,
                    "annual_property_tax": parcel.annual_property_tax,
                    "census_tract": parcel.census_tract, "census_block": parcel.census_block,
                    "property_use_code": parcel.property_use_code,
                    "match_method": "unique closest-year municipality+block+lot",
                    "source_hash": sale.source_hash,
                }

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply-migration", action="store_true")
    parser.add_argument("--load", action="store_true")
    parser.add_argument("--years", nargs="*", type=int)
    args = parser.parse_args()
    if not args.apply_migration and not args.load:
        parser.error("select --apply-migration and/or --load")
    connection = engine.raw_connection()
    try:
        if args.apply_migration:
            apply_migration(connection)
            print("Migration 007 applied", flush=True)
        if args.load:
            count = _copy_rows(connection, "nj_avm_training_sales", COLUMNS,
                               training_rows(set(args.years) if args.years else None))
            print(f"AVM training rows processed: {count}", flush=True)
    finally:
        connection.close()

if __name__ == "__main__":
    main()
