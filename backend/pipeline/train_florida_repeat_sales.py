"""Evaluate a low-history Florida repeat-sale, county-trend valuation candidate.

This estimates only parcels with an earlier qualifying sale. It is not a
property-feature AVM and is deliberately not registered as a promoted model.
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text

from app.database.session import warehouse_engine
from pipeline.train_state_avms import MODEL_DIR, regression_metrics

SALES_SQL = text("""
SELECT id,county,source_parcel_id,sale_date,sale_price
FROM public_property_sales
WHERE state='FL' AND source_id='fl_dor_sdf_2026p' AND arms_length IS TRUE
  AND (conveyance_code LIKE 'qual:01%' OR conveyance_code LIKE 'qual:02%')
  AND conveyance_code LIKE '%property:I%'
  AND conveyance_code NOT LIKE '%change:%'
  AND sale_price BETWEEN 25000 AND 10000000
  AND sale_date BETWEEN DATE '2025-01-01' AND DATE '2026-05-31'
  AND MOD(ABS(HASHTEXT(county || ':' || source_parcel_id)::bigint),100) < :sample_percent
ORDER BY county,source_parcel_id,sale_date,id
""")
VALIDATION_START = pd.Timestamp("2026-03-01")
TEST_START = pd.Timestamp("2026-04-01")
TEST_END = pd.Timestamp("2026-06-01")


def prepare_sales(sales: pd.DataFrame) -> pd.DataFrame:
    frame = sales.copy()
    frame["sale_date"] = pd.to_datetime(frame.sale_date)
    frame["sale_price"] = pd.to_numeric(frame.sale_price)
    frame = frame.sort_values(["county", "source_parcel_id", "sale_date", "id"])
    frame = frame.drop_duplicates(["county", "source_parcel_id", "sale_date", "sale_price"])
    grouped = frame.groupby(["county", "source_parcel_id"], sort=False)
    frame["prior_sale_date"] = grouped.sale_date.shift()
    frame["prior_sale_price"] = grouped.sale_price.shift()
    frame["sale_month"] = frame.sale_date.dt.to_period("M")
    frame["prior_month"] = frame.prior_sale_date.dt.to_period("M")
    return frame


def county_month_indices(history: pd.DataFrame, through: pd.Timestamp,
                         months: int) -> tuple[dict[tuple[str, pd.Period], float], dict[str, float]]:
    """Trailing county medians; each historical index uses only data available by then."""
    past = history.loc[history.sale_date < through].copy()
    counties = {}
    indices = {}
    current_month = through.to_period("M") - 1
    for county, group in past.groupby("county"):
        counties[county] = float(group.sale_price.median())
        for month in group.sale_month.unique():
            lower = month - (months - 1)
            recent = group.loc[group.sale_month.between(lower, month), "sale_price"]
            indices[(county, month)] = float(recent.median())
        recent = group.loc[group.sale_month.between(current_month - (months - 1), current_month), "sale_price"]
        if not recent.empty:
            indices[(county, current_month)] = float(recent.median())
    return indices, counties


def evaluate_window(frame: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp,
                    cutoff: pd.Timestamp, months: int) -> dict:
    indices, county_medians = county_month_indices(frame, cutoff, months)
    current_month = cutoff.to_period("M") - 1
    target = frame.loc[(frame.sale_date >= start) & (frame.sale_date < end)
                       & (frame.prior_sale_date < cutoff)
                       & (frame.prior_sale_date < frame.sale_date)].copy()
    records = []
    for row in target.itertuples():
        prior_index = indices.get((row.county, row.prior_month))
        current_index = indices.get((row.county, current_month))
        if not prior_index or not current_index or not np.isfinite(row.prior_sale_price):
            continue
        # Limit extrapolation caused by a changed mix of homes sold in a county.
        ratio = float(np.clip(current_index / prior_index, 0.75, 1.25))
        records.append((row.sale_price, row.prior_sale_price * ratio,
                        row.prior_sale_price, county_medians[row.county]))
    if not records:
        return {"rows": 0, "reason": "no qualifying repeat sales with county history"}
    values = np.asarray(records)
    return {"rows": len(values), "county_index_adjusted": regression_metrics(values[:, 0], values[:, 1]),
            "unchanged_prior_sale": regression_metrics(values[:, 0], values[:, 2]),
            "county_median": regression_metrics(values[:, 0], values[:, 3])}


def train(sample_percent: int = 10, output_dir: Path = MODEL_DIR) -> dict:
    with warehouse_engine.connect() as connection:
        frame = pd.read_sql(SALES_SQL, connection, params={"sample_percent": sample_percent})
    frame = prepare_sales(frame)
    candidates = {str(months): evaluate_window(
        frame, VALIDATION_START, TEST_START, VALIDATION_START, months)
        for months in (1, 3, 6)}
    qualified = [(result["county_index_adjusted"]["mae"], months)
                 for months, result in candidates.items() if result["rows"] >= 100]
    selected = min(qualified)[1] if qualified else None
    test = (evaluate_window(frame, TEST_START, TEST_END, TEST_START, int(selected))
            if selected else {"rows": 0, "reason": "insufficient validation repeat sales"})
    passed = (test["rows"] >= 250
              and test["county_index_adjusted"]["mae"] < test["unchanged_prior_sale"]["mae"]
              and test["county_index_adjusted"]["within_20_percent"] >= 50)
    report = {
        "state": "FL", "model": "county-index-adjusted repeat sale",
        "status": "ELIGIBLE_FOR_REVIEW" if passed else "REJECTED",
        "trained_at": datetime.now(UTC).isoformat(), "sample_percent": sample_percent,
        "sale_rows": len(frame), "qualifying_repeat_sales": int(frame.prior_sale_price.notna().sum()),
        "validation": "2026-03; county history through 2026-02",
        "test": "2026-04..2026-05; county history through 2026-03",
        "selected_trailing_months": int(selected) if selected else None,
        "validation_candidates": candidates, "test_metrics": test,
        "promotion_gate": {"rule": "at least 250 test repeat sales, lower MAE than unchanged prior sale, and at least 50% within 20%",
                           "passed": passed},
        "limitations": ["Only parcels with a prior qualifying sale since 2025-01 can be estimated",
                        "County sale mix changes can distort price trends",
                        "May 2026 is the last complete sale month in the current feed",
                        "Not an individual property-feature AVM or appraisal"],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "fl_repeat_sales_experimental_metrics.json").write_text(
        json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample-percent", type=int, default=10)
    parser.add_argument("--output-dir", type=Path, default=MODEL_DIR)
    args = parser.parse_args()
    if not 1 <= args.sample_percent <= 100:
        parser.error("--sample-percent must be between 1 and 100")
    print(json.dumps(train(args.sample_percent, args.output_dir), indent=2))


if __name__ == "__main__":
    main()
