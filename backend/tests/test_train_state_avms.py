from datetime import date

import pandas as pd

from pipeline.train_state_avms import (
    baseline, chronological_split, passes_promotion_gate, prepare, regression_metrics,
    residential_sales,
)
from pipeline.state_avm_scope import residential_scope


def test_chronological_split_reserves_last_twelve_months() -> None:
    frame = pd.DataFrame({"sale_date": ["2022-01-01", "2023-08-03", "2024-08-02", "2025-08-01"],
                          "sale_price": [1, 2, 3, 4]})
    split = chronological_split(frame, date(2025, 8, 1))
    assert split.train.sale_price.tolist() == [1]
    assert split.validation.sale_price.tolist() == [2]
    assert split.test.sale_price.tolist() == [3, 4]
    assert split.test.sale_date.min() >= split.test_start


def test_split_uses_requested_as_of_even_if_sales_feed_is_stale() -> None:
    frame = pd.DataFrame({"sale_date": ["2020-01-01", "2022-01-01", "2024-01-01"],
                          "sale_price": [1, 2, 3]})
    split = chronological_split(frame, date(2026, 9, 16))
    assert split.test.empty
    assert split.test_start == pd.Timestamp("2025-09-16")


def test_prepare_features_and_prior_county_baseline() -> None:
    frame = pd.DataFrame([
        {"sale_date": "2020-01-01", "sale_price": 100000, "county": "A", "year_built": 1990,
         "living_area": 1000},
        {"sale_date": "2020-02-01", "sale_price": 200000, "county": "A", "year_built": 1980,
         "living_area": 1500},
    ])
    for column in ("land_area", "bedrooms", "bathrooms", "rooms", "land_value", "improvement_value",
                   "total_assessed_value", "latitude", "longitude", "zip_code", "city", "property_type",
                   "land_use_code", "school_district_code", "school_district_name"):
        frame[column] = None
    clean, audit = prepare(frame)
    assert clean.property_age.tolist() == [30, 40]
    assert audit["eligible_rows"] == 2
    assert baseline(clean, clean).tolist() == [150000, 150000]
    assert regression_metrics([100, 200], [110, 190])["mae"] == 10


def test_prepare_rejects_prior_sale_on_or_after_target_date() -> None:
    row = {"sale_date": "2024-03-01", "sale_price": 250000, "county": "A",
           "prior_sale_date": "2024-03-01", "prior_sale_price": 200000,
           "year_built": 1980, "living_area": 1200}
    for column in ("land_area", "bedrooms", "bathrooms", "rooms", "land_value",
                   "improvement_value", "total_assessed_value", "latitude", "longitude",
                   "zip_code", "city", "property_type", "land_use_code",
                   "school_district_code", "school_district_name"):
        row[column] = None
    clean, _ = prepare(pd.DataFrame([row]))
    assert pd.isna(clean.prior_sale_price.iloc[0])


def test_promotion_requires_both_baseline_improvement_and_coverage() -> None:
    metrics = {"test": {"xgboost": {"mae": 100, "within_20_percent": 49.9},
                        "prior_county_median": {"mae": 150}}}
    assert not passes_promotion_gate(metrics)
    metrics["test"]["xgboost"]["within_20_percent"] = 50
    assert passes_promotion_gate(metrics)


def test_residential_class_scope() -> None:
    assert residential_scope("NY", "ny_orpts_salesweb_rp5217", "210")
    assert residential_scope("NY", "ny_orpts_local_assessment_rolls_2021_2025", "210")
    assert not residential_scope("NY", "ny_orpts_salesweb_rp5217", "311")
    assert not residential_scope("NY", "ny_nyc_acris", "210")
    assert residential_scope("IL", "il_cook_assessor_1999_present", "299")
    assert not residential_scope("IL", "il_cook_assessor_1999_present", "200")
    assert residential_scope("IL", "il_idor_mydec_2014_present", "b")


def test_residential_sales_requires_explicit_market_sale_and_dedupes() -> None:
    rows = pd.DataFrame([
        {"sale_id": 1, "sale_source_id": "il_idor_mydec_2014_present", "snapshot_source_id": "il_idor_mydec_2014_present", "arms_length": True, "county": "Lake", "source_parcel_id": "1", "sale_date": "2025-01-01", "sale_price": 300000, "land_use_code": "B"},
        {"sale_id": 2, "sale_source_id": "il_idor_mydec_2014_present", "snapshot_source_id": "il_idor_mydec_2014_present", "arms_length": True, "county": "Lake", "source_parcel_id": "1", "sale_date": "2025-01-01", "sale_price": 300000, "land_use_code": "B"},
        {"sale_id": 3, "sale_source_id": "il_idor_mydec_2014_present", "snapshot_source_id": "il_idor_mydec_2014_present", "arms_length": None, "county": "Lake", "source_parcel_id": "2", "sale_date": "2025-01-02", "sale_price": 300000, "land_use_code": "B"},
        {"sale_id": 4, "sale_source_id": "il_idor_mydec_2014_present", "snapshot_source_id": "il_idor_mydec_2014_present", "arms_length": True, "county": "Lake", "source_parcel_id": "3", "sale_date": "2025-01-03", "sale_price": 300000, "land_use_code": "A"},
    ])
    clean, audit = residential_sales(rows, "IL")
    assert clean.sale_id.tolist() == [1]
    assert audit["duplicate_sale_events_removed"] == 1
