"""Load Monmouth MOD-IV/SR-1A history and build conservative parcel matches."""
from __future__ import annotations

import argparse
import csv
import io
from pathlib import Path

from app.database.session import engine
from pipeline.nj_property_records import parse_modiv, parse_sr1a, records

BACKEND = Path(__file__).resolve().parents[1]
RAW = BACKEND / "data" / "nj_property" / "raw"
MIGRATION = BACKEND / "migrations" / "006_nj_property_history.sql"
MODIV_FILES = {
    2021: RAW / "modiv/2021/Monmouth21re.txt",
    2022: RAW / "modiv/2022/Monmouth22re.txt",
    2023: RAW / "modiv/2023/Monmouth23re.txt",
    2024: RAW / "modiv/2024/Monmouth 24re.txt",
    2025: RAW / "modiv/2025/MonmouthRE.txt",
    2026: RAW / "modiv/2026/Monmouth 26 RE.txt",
}
SR1A_FILES = {
    2020: RAW / "sr1a/2020/Sales2020.txt", 2021: RAW / "sr1a/2021/Sales2021.txt",
    2022: RAW / "sr1a/2022/Sales2022.txt", 2023: RAW / "sr1a/2023/Sales2023.txt",
    2024: RAW / "sr1a/2024/Sales2024.txt", 2025: RAW / "sr1a/2025/Sales2025.txt",
    2026: RAW / "sr1a/2026/YTDSR1A2026.txt",
}
MODIV_COLUMNS = ["source_year","municipality_code","block","lot","qualifier","record_id",
    "property_class","property_location","building_description","land_description","acreage",
    "zoning","deed_date","sale_price","sale_nonusable_code","building_class","year_built",
    "land_assessed","improvement_assessed","total_assessed","census_tract","census_block",
    "property_use_code","annual_property_tax","source_file","source_line_number","source_hash"]
SR1A_COLUMNS = ["source_year","county_code","district_code","municipality_code","block","lot",
    "property_location","deed_date","recorded_date","reported_price","verified_price","land_assessed",
    "improvement_assessed","total_assessed","assessment_year","property_class","qualification_codes",
    "year_built","living_space","source_file","source_line_number","source_hash"]

def apply_migration(connection) -> None:
    with connection.cursor() as cursor: cursor.execute(MIGRATION.read_text())
    connection.commit()

def _copy_rows(connection, table: str, columns: list[str], rows, predicate=lambda row: True,
               chunk_size: int = 10_000) -> int:
    total, batch = 0, []
    with connection.cursor() as cursor:
        cursor.execute(f"CREATE TEMP TABLE import_rows (LIKE {table} INCLUDING DEFAULTS) ON COMMIT DROP")
        for row in rows:
            if not predicate(row): continue
            batch.append(row)
            if len(batch) >= chunk_size:
                total += _flush(cursor, table, columns, batch); batch.clear(); connection.commit()
                cursor.execute(f"CREATE TEMP TABLE import_rows (LIKE {table} INCLUDING DEFAULTS) ON COMMIT DROP")
        if batch: total += _flush(cursor, table, columns, batch)
    connection.commit()
    return total

def _flush(cursor, table: str, columns: list[str], batch: list[dict]) -> int:
    stream = io.StringIO(); writer = csv.writer(stream, lineterminator="\n")
    for row in batch:
        writer.writerow(["\\N" if row[name] is None else row[name] for name in columns])
    stream.seek(0); names = ",".join(columns)
    cursor.copy_expert(f"COPY import_rows ({names}) FROM STDIN WITH (FORMAT CSV, NULL '\\N')", stream)
    cursor.execute(f"INSERT INTO {table} ({names}) SELECT {names} FROM import_rows ON CONFLICT DO NOTHING")
    cursor.execute("TRUNCATE import_rows")
    return len(batch)

def rebuild_matches(connection) -> None:
    sql = """
    TRUNCATE nj_sr1a_modiv_matches;
    WITH available_years AS (
      SELECT DISTINCT source_year FROM nj_modiv_parcel_snapshots
    ), target_year AS (
      SELECT s.id, (SELECT y.source_year FROM available_years y
        ORDER BY ABS(y.source_year-s.source_year), y.source_year LIMIT 1) AS modiv_year
      FROM nj_sr1a_sales s
    ), candidates AS (
      SELECT s.id AS sale_id, COUNT(m.id)::int AS candidate_count, MIN(m.id) AS candidate_id
      FROM nj_sr1a_sales s JOIN target_year y ON y.id=s.id
      LEFT JOIN nj_modiv_parcel_snapshots m ON m.source_year=y.modiv_year
        AND m.municipality_code=s.municipality_code AND m.block=s.block AND m.lot=s.lot
      GROUP BY s.id
    )
    INSERT INTO nj_sr1a_modiv_matches
      (sr1a_sale_id,modiv_snapshot_id,match_status,candidate_count,match_method)
    SELECT sale_id, CASE WHEN candidate_count=1 THEN candidate_id END,
      CASE WHEN candidate_count=1 THEN 'EXACT' WHEN candidate_count>1 THEN 'AMBIGUOUS' ELSE 'UNMATCHED' END,
      candidate_count, 'closest-year municipality+block+lot'
    FROM candidates;
    """
    with connection.cursor() as cursor: cursor.execute(sql)
    connection.commit()

def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument("--apply-migration",action="store_true")
    parser.add_argument("--load",action="store_true")
    parser.add_argument("--rebuild-matches",action="store_true")
    parser.add_argument("--years",nargs="*",type=int)
    args=parser.parse_args()
    if not any((args.apply_migration,args.load,args.rebuild_matches)): parser.error("select an action")
    connection=engine.raw_connection()
    try:
        if args.apply_migration: apply_migration(connection); print("Migration 006 applied")
        if args.load:
            years=set(args.years or MODIV_FILES)
            for year,path in MODIV_FILES.items():
                if year in years:
                    count=_copy_rows(connection,"nj_modiv_parcel_snapshots",MODIV_COLUMNS,
                        records(path,parse_modiv,year)); print(f"MOD-IV {year}: processed {count}")
            sr_years=set(args.years or SR1A_FILES)
            for year,path in SR1A_FILES.items():
                if year in sr_years:
                    count=_copy_rows(connection,"nj_sr1a_sales",SR1A_COLUMNS,
                        records(path,parse_sr1a,year),lambda row: row["county_code"]=="13")
                    print(f"SR-1A {year}: processed {count} Monmouth records")
        if args.rebuild_matches: rebuild_matches(connection); print("Parcel matches rebuilt")
    finally: connection.close()

if __name__ == "__main__": main()
