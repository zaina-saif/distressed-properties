"""Train an explicitly limited Monroe KIZ baseline AVM."""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.base import clone
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from sqlalchemy import text


BACKEND = Path(__file__).resolve().parents[1]
MODEL_DIR = BACKEND / "data" / "pa_property" / "models"
NUMERIC_FEATURES = [
    "acreage", "assessed_value", "land_value", "improvement_value",
    "latitude", "longitude", "sale_year", "sale_month",
]
CATEGORICAL_FEATURES = ["property_type", "land_use_code"]
QUERY = """
SELECT parcel_id,sale_date,sale_price,acreage,assessed_value,land_value,
       improvement_value,latitude,longitude,sale_year,sale_month,
       property_type,land_use_code
FROM pa_avm_training_sales
WHERE eligible_for_baseline
ORDER BY sale_date,parcel_id
"""


def chronological_split(frame: pd.DataFrame):
    return (
        frame[frame.sale_year <= 2020].copy(),
        frame[frame.sale_year == 2021].copy(),
        frame[frame.sale_year == 2022].copy(),
    )


def metrics(actual, predicted) -> dict[str, float]:
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    errors = np.abs(actual - predicted)
    denominator = np.maximum(np.abs(actual), 1)
    return {
        "mae": round(float(mean_absolute_error(actual, predicted)), 2),
        "rmse": round(float(mean_squared_error(actual, predicted) ** 0.5), 2),
        "median_absolute_error": round(float(np.median(errors)), 2),
        "mape_percent": round(float(np.mean(errors / denominator) * 100), 2),
        "within_10_percent": round(float(np.mean(errors / denominator <= 0.10) * 100), 2),
        "within_20_percent": round(float(np.mean(errors / denominator <= 0.20) * 100), 2),
        "r2": round(float(r2_score(actual, predicted)), 4),
    }


def train(output_dir: Path = MODEL_DIR) -> dict:
    from app.database.session import engine
    from xgboost import XGBRegressor
    with engine.connect() as connection:
        frame = pd.read_sql(text(QUERY), connection)
    train_frame, validation_frame, test_frame = chronological_split(frame)
    if min(len(train_frame), len(validation_frame), len(test_frame)) == 0:
        raise RuntimeError("Monroe chronological split produced an empty partition")

    transformer = ColumnTransformer([
        ("numeric", Pipeline([("impute", SimpleImputer(strategy="median"))]), NUMERIC_FEATURES),
        ("categorical", Pipeline([
            ("impute", SimpleImputer(strategy="most_frequent")),
            ("onehot", OneHotEncoder(handle_unknown="ignore")),
        ]), CATEGORICAL_FEATURES),
    ])
    pipeline = Pipeline([
        ("features", transformer),
        ("model", XGBRegressor(
            n_estimators=450, learning_rate=0.03, max_depth=3,
            min_child_weight=6, subsample=0.85, colsample_bytree=0.85,
            objective="reg:absoluteerror", eval_metric="mae",
            random_state=42, n_jobs=-1,
        )),
    ])
    features = NUMERIC_FEATURES + CATEGORICAL_FEATURES
    pipeline.fit(train_frame[features], train_frame.sale_price)
    log_pipeline = clone(pipeline)
    log_pipeline.fit(train_frame[features], np.log1p(train_frame.sale_price))
    training_median_ratio = float(
        np.median(train_frame.sale_price / train_frame.assessed_value)
    )
    report = {
        "trained_at": datetime.now(UTC).isoformat(),
        "model": "XGBRegressor",
        "model_status": "evaluation_pending",
        "target": "sale_price",
        "source": "Monroe County KIZ Parcels (2022 snapshot)",
        "split": {"train": "2017-2020", "validation": "2021", "test": "2022"},
        "rows": {
            "train": len(train_frame), "validation": len(validation_frame),
            "test": len(test_frame), "total": len(frame),
        },
        "features": features,
        "limitations": [
            "KIZ is a 2,187-parcel geographic subset, not countywide training data",
            "land-use codes are retained as raw categories because no official codebook was located",
            "building square footage, bedrooms, bathrooms, and year built are unavailable",
            "latest training transaction is 2022-07-26",
        ],
        "metrics": {},
    }
    for name, subset in (("validation", validation_frame), ("test", test_frame)):
        prediction = pipeline.predict(subset[features])
        log_prediction = np.expm1(log_pipeline.predict(subset[features]))
        assessed = subset.assessed_value.to_numpy(dtype=float)
        ratio_baseline = assessed * training_median_ratio
        report["metrics"][name] = {
            "xgboost": metrics(subset.sale_price, prediction),
            "xgboost_log_target": metrics(subset.sale_price, log_prediction),
            "assessed_value": metrics(subset.sale_price, assessed),
            "training_median_ratio": metrics(subset.sale_price, ratio_baseline),
        }

    selected_name, selected_pipeline, target_transform = min(
        (
            ("xgboost", pipeline, "identity"),
            ("xgboost_log_target", log_pipeline, "log1p"),
        ),
        key=lambda candidate: report["metrics"]["validation"][candidate[0]]["mae"],
    )
    beats_baseline = all(
        report["metrics"][partition][selected_name]["mae"]
        < report["metrics"][partition]["training_median_ratio"]["mae"]
        for partition in ("validation", "test")
    )
    report["selected_candidate"] = selected_name
    report["promotion_gate"] = {
        "rule": "selected candidate MAE must beat training-median assessment ratio on validation and test",
        "passed": beats_baseline,
    }
    report["model_status"] = (
        "experimental_kiz_subset_only" if beats_baseline else "rejected_not_for_valuation"
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump({
        "pipeline": selected_pipeline,
        "features": features,
        "model_status": report["model_status"],
        "target_transform": target_transform,
        "training_data_as_of": "2022-07-26",
    }, output_dir / "monroe_kiz_avm_xgboost.joblib")
    (output_dir / "monroe_kiz_avm_metrics.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=MODEL_DIR)
    args = parser.parse_args()
    print(json.dumps(train(args.output_dir), indent=2))


if __name__ == "__main__":
    main()
