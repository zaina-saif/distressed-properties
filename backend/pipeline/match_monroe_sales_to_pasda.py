"""Match Monroe sheriff sales to PASDA parcels using deterministic identifiers only."""
from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import text

from app.database.session import engine


MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "015_pa_sheriff_sale_parcel_fields.sql"


def apply_migration() -> None:
    with engine.begin() as connection:
        connection.execute(text(MIGRATION.read_text()))


def match_sales() -> dict[str, int]:
    with engine.begin() as connection:
        connection.execute(text("""DELETE FROM pa_sheriff_sale_parcel_matches m
          USING sheriff_sales s WHERE m.sheriff_sale_id=s.id
          AND s.state='PA' AND s.county='Monroe'"""))
        exact = connection.execute(text("""INSERT INTO pa_sheriff_sale_parcel_matches(
          sheriff_sale_id,parcel_id,raw_map_number,normalized_map_number,match_method,match_status)
          SELECT s.id,p.id,s.map_number,s.normalized_map_number,'raw map number equality','EXACT'
          FROM sheriff_sales s JOIN pa_parcels p ON p.state=s.state AND p.county=s.county
            AND p.map_number=s.map_number
          WHERE s.state='PA' AND s.county='Monroe' AND s.map_number IS NOT NULL
          ON CONFLICT(sheriff_sale_id,parcel_id) DO UPDATE SET updated_at=NOW()
          RETURNING id""")).rowcount
        normalized = connection.execute(text("""INSERT INTO pa_sheriff_sale_parcel_matches(
          sheriff_sale_id,parcel_id,raw_map_number,normalized_map_number,match_method,match_status)
          SELECT s.id,p.id,s.map_number,s.normalized_map_number,'normalized map number equality','NORMALIZED'
          FROM sheriff_sales s JOIN pa_parcels p ON p.state=s.state AND p.county=s.county
            AND p.normalized_map_number=s.normalized_map_number
          WHERE s.state='PA' AND s.county='Monroe' AND s.normalized_map_number IS NOT NULL
            AND NOT EXISTS(SELECT 1 FROM pa_sheriff_sale_parcel_matches m WHERE m.sheriff_sale_id=s.id)
          ON CONFLICT(sheriff_sale_id,parcel_id) DO UPDATE SET updated_at=NOW()
          RETURNING id""")).rowcount
        crosswalk = connection.execute(text("""INSERT INTO pa_sheriff_sale_parcel_matches(
          sheriff_sale_id,parcel_id,raw_map_number,normalized_map_number,match_method,match_status)
          SELECT s.id,d.parcel_id,s.map_number,s.normalized_map_number,
            'Monroe County KIZ PARID crosswalk','NORMALIZED'
          FROM sheriff_sales s JOIN pa_property_details d
            ON d.normalized_tax_parcel_id=s.normalized_map_number
          WHERE s.state='PA' AND s.county='Monroe' AND s.normalized_map_number IS NOT NULL
            AND NOT EXISTS(SELECT 1 FROM pa_sheriff_sale_parcel_matches m WHERE m.sheriff_sale_id=s.id)
          ON CONFLICT(sheriff_sale_id,parcel_id) DO UPDATE SET updated_at=NOW()
          RETURNING id""")).rowcount
        total = connection.execute(text("""SELECT COUNT(*) FROM sheriff_sales
          WHERE state='PA' AND county='Monroe'""")).scalar_one()
        missing_map_number = connection.execute(text("""SELECT COUNT(*) FROM sheriff_sales
          WHERE state='PA' AND county='Monroe' AND normalized_map_number IS NULL""")).scalar_one()
    return {"sales": total, "exact": exact, "normalized": normalized,
            "official_crosswalk": crosswalk,
            "unmatched": total - exact - normalized - crosswalk,
            "missing_map_number": missing_map_number}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply-migration", action="store_true")
    args = parser.parse_args()
    if args.apply_migration:
        apply_migration()
        print("Migration 015 applied")
    print("Monroe PASDA match complete:", match_sales())


if __name__ == "__main__":
    main()
