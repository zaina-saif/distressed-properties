"""Prepare an auditable baseline AVM dataset from Monroe KIZ assessment records."""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from sqlalchemy import text


MIGRATIONS = [
    Path(__file__).resolve().parents[1] / "migrations" / "017_monroe_avm_training.sql",
    Path(__file__).resolve().parents[1] / "migrations" / "018_monroe_land_use.sql",
]
PREPARATION_VERSION = "monroe_kiz_baseline_v1"
MINIMUM_PRICE = 1_000
MAXIMUM_PRICE = 5_000_000
MINIMUM_RATIO = 0.1
MAXIMUM_RATIO = 10.0


def training_window_start(dataset_as_of: date, years: int = 5) -> date:
    return date(dataset_as_of.year - years, 1, 1)


def apply_migration() -> None:
    from app.database.session import engine
    with engine.begin() as connection:
        for migration in MIGRATIONS:
            connection.execute(text(migration.read_text()))


def prepare_training_data() -> dict:
    from app.database.session import engine
    with engine.begin() as connection:
        dataset_as_of = connection.execute(text("""SELECT MAX(d.last_sale_date)
          FROM pa_property_details d JOIN pa_parcels p ON p.id=d.parcel_id
          WHERE p.state='PA' AND p.county='Monroe'""")).scalar_one()
        if dataset_as_of is None:
            raise RuntimeError("No Monroe sale dates are available")
        window_start = training_window_start(dataset_as_of)
        params = {
            "dataset_as_of": dataset_as_of,
            "window_start": window_start,
            "minimum_price": MINIMUM_PRICE,
            "maximum_price": MAXIMUM_PRICE,
            "minimum_ratio": MINIMUM_RATIO,
            "maximum_ratio": MAXIMUM_RATIO,
            "version": PREPARATION_VERSION,
        }
        connection.execute(text("""INSERT INTO pa_avm_training_sales(
          property_detail_id,parcel_id,tax_parcel_id,property_location,latitude,longitude,
          property_type,land_use_code,acreage,assessed_value,land_value,improvement_value,sale_date,
          sale_price,sale_year,sale_month,sale_to_assessed_ratio,dataset_as_of,
          training_window_start,eligible_for_baseline,exclusion_reasons,warning_flags,
          preparation_version,prepared_at)
          SELECT d.id,d.parcel_id,d.tax_parcel_id,d.property_location,p.latitude,p.longitude,
            d.property_type,d.land_use_code,d.acreage,d.assessed_value,d.land_value,d.improvement_value,
            d.last_sale_date,d.last_sale_price,EXTRACT(YEAR FROM d.last_sale_date)::int,
            EXTRACT(MONTH FROM d.last_sale_date)::int,
            ROUND(d.last_sale_price/NULLIF(d.assessed_value,0),6),
            :dataset_as_of,:window_start,
            d.last_sale_date BETWEEN :window_start AND :dataset_as_of
              AND d.last_sale_price BETWEEN :minimum_price AND :maximum_price
              AND d.assessed_value>0
              AND d.last_sale_price/NULLIF(d.assessed_value,0)
                BETWEEN :minimum_ratio AND :maximum_ratio,
            TO_JSONB(ARRAY_REMOVE(ARRAY[
              CASE WHEN d.last_sale_date IS NULL THEN 'missing_sale_date' END,
              CASE WHEN d.last_sale_date<:window_start THEN 'outside_five_year_window' END,
              CASE WHEN d.last_sale_date>:dataset_as_of THEN 'sale_after_dataset_as_of' END,
              CASE WHEN d.last_sale_price IS NULL THEN 'missing_sale_price' END,
              CASE WHEN d.last_sale_price IS NOT NULL AND d.last_sale_price<:minimum_price
                THEN 'nominal_or_low_value_transfer' END,
              CASE WHEN d.last_sale_price>:maximum_price THEN 'sale_price_above_baseline_cap' END,
              CASE WHEN d.assessed_value IS NULL OR d.assessed_value<=0
                THEN 'missing_or_nonpositive_assessment' END,
              CASE WHEN d.last_sale_price>=:minimum_price AND d.assessed_value>0
                AND d.last_sale_price/d.assessed_value NOT BETWEEN :minimum_ratio AND :maximum_ratio
                THEN 'sale_to_assessment_ratio_outlier' END
            ],NULL)),
            TO_JSONB(ARRAY_REMOVE(ARRAY[
              CASE WHEN d.acreage IS NULL OR d.acreage<=0 THEN 'missing_or_nonpositive_acreage' END,
              CASE WHEN d.property_type IS NULL OR BTRIM(d.property_type)='' THEN 'missing_property_type' END,
              CASE WHEN d.land_use_code IS NULL OR BTRIM(d.land_use_code)='' THEN 'missing_land_use_code' END,
              CASE WHEN d.property_location IS NULL OR BTRIM(d.property_location)=''
                THEN 'missing_property_location' END
            ],NULL)),:version,NOW()
          FROM pa_property_details d JOIN pa_parcels p ON p.id=d.parcel_id
          WHERE p.state='PA' AND p.county='Monroe'
          ON CONFLICT(property_detail_id) DO UPDATE SET
            parcel_id=EXCLUDED.parcel_id,tax_parcel_id=EXCLUDED.tax_parcel_id,
            property_location=EXCLUDED.property_location,latitude=EXCLUDED.latitude,
            longitude=EXCLUDED.longitude,property_type=EXCLUDED.property_type,
            land_use_code=EXCLUDED.land_use_code,
            acreage=EXCLUDED.acreage,assessed_value=EXCLUDED.assessed_value,
            land_value=EXCLUDED.land_value,improvement_value=EXCLUDED.improvement_value,
            sale_date=EXCLUDED.sale_date,sale_price=EXCLUDED.sale_price,
            sale_year=EXCLUDED.sale_year,sale_month=EXCLUDED.sale_month,
            sale_to_assessed_ratio=EXCLUDED.sale_to_assessed_ratio,
            dataset_as_of=EXCLUDED.dataset_as_of,training_window_start=EXCLUDED.training_window_start,
            eligible_for_baseline=EXCLUDED.eligible_for_baseline,
            exclusion_reasons=EXCLUDED.exclusion_reasons,warning_flags=EXCLUDED.warning_flags,
            preparation_version=EXCLUDED.preparation_version,prepared_at=NOW()"""), params)
        summary = connection.execute(text("""SELECT COUNT(*) AS total,
          COUNT(*) FILTER(WHERE eligible_for_baseline) AS eligible,
          COUNT(*) FILTER(WHERE NOT eligible_for_baseline) AS excluded,
          COUNT(*) FILTER(WHERE JSONB_ARRAY_LENGTH(warning_flags)>0) AS with_warnings,
          MIN(sale_date) FILTER(WHERE eligible_for_baseline) AS earliest_eligible_sale,
          MAX(sale_date) FILTER(WHERE eligible_for_baseline) AS latest_eligible_sale
          FROM pa_avm_training_sales WHERE preparation_version=:version"""), params).mappings().one()
        reasons = connection.execute(text("""SELECT reason,COUNT(*) AS records
          FROM pa_avm_training_sales t CROSS JOIN LATERAL
            JSONB_ARRAY_ELEMENTS_TEXT(t.exclusion_reasons) AS reasons(reason)
          WHERE t.preparation_version=:version GROUP BY reason ORDER BY records DESC,reason"""),
          params).mappings()
    return {**dict(summary), "dataset_as_of": dataset_as_of,
            "training_window_start": window_start,
            "exclusion_reason_counts": [dict(row) for row in reasons]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply-migration", action="store_true")
    args = parser.parse_args()
    if args.apply_migration:
        apply_migration()
        print("Monroe AVM migrations applied")
    print("Monroe AVM training preparation complete:", prepare_training_data())


if __name__ == "__main__":
    main()
