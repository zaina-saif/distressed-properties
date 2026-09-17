"""Train and evaluate independent leakage-safe XGBoost AVMs by state."""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from sqlalchemy import text
from xgboost import XGBRegressor

from app.database.session import warehouse_engine
from pipeline.state_avm_scope import IL_COOK, IL_MYDEC, NY_SALESWEB, residential_scope

BACKEND = Path(__file__).resolve().parents[1]
MODEL_DIR = BACKEND / "data" / "state_avm" / "models"
STATES = ("MD", "FL", "OH", "VA", "DC", "IL", "NY")
NUMERIC_FEATURES = (
    "living_area", "land_area", "bedrooms", "bathrooms", "rooms", "year_built",
    "land_value", "improvement_value", "total_assessed_value", "latitude", "longitude",
    "sale_month", "sale_year", "property_age", "prior_sale_price", "prior_sale_age_years",
)
CATEGORICAL_FEATURES = (
    "county", "zip_code", "city", "property_type", "land_use_code",
    "school_district_code", "school_district_name",
)
FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES
TRAINING_SQL = text("""
SELECT s.id AS sale_id,s.source_id AS sale_source_id,s.arms_length,s.county,
       s.source_parcel_id,s.sale_date,s.sale_price,
       p.source_id AS snapshot_source_id,p.zip_code,p.city,p.property_type,p.land_use_code,p.year_built,p.living_area,
       p.land_area,p.bedrooms,p.bathrooms,p.rooms,p.land_value,p.improvement_value,
       p.total_assessed_value,p.latitude,p.longitude,p.school_district_code,
       p.school_district_name,p.snapshot_year,
       previous.sale_date AS prior_sale_date,previous.sale_price AS prior_sale_price
FROM public_property_sales s
LEFT JOIN LATERAL (
    SELECT ps.* FROM public_property_snapshots ps
    WHERE ps.state=s.state AND ps.county=s.county
      AND ps.source_parcel_id=s.source_parcel_id
      AND ps.snapshot_year < EXTRACT(YEAR FROM s.sale_date)
    ORDER BY (CASE WHEN ps.living_area IS NOT NULL THEN 1 ELSE 0 END
            + CASE WHEN ps.bedrooms IS NOT NULL THEN 1 ELSE 0 END
            + CASE WHEN ps.bathrooms IS NOT NULL THEN 1 ELSE 0 END
            + CASE WHEN ps.year_built IS NOT NULL THEN 1 ELSE 0 END) DESC,
            ps.snapshot_year DESC,ps.imported_at DESC LIMIT 1
) p ON TRUE
LEFT JOIN LATERAL (
    SELECT prior.sale_date,prior.sale_price FROM public_property_sales prior
    WHERE prior.state=s.state AND prior.county=s.county
      AND prior.source_parcel_id=s.source_parcel_id
      AND prior.sale_date<s.sale_date AND prior.sale_price BETWEEN 10000 AND 50000000
      AND prior.transaction_id<>s.transaction_id
      AND (prior.arms_length IS NULL OR prior.arms_length)
    ORDER BY prior.sale_date DESC,prior.id DESC LIMIT 1
) previous ON TRUE
WHERE s.state=:state AND s.sale_price BETWEEN 10000 AND 50000000
  AND s.sale_date BETWEEN DATE '2020-01-01' AND :as_of
  AND (s.arms_length IS NULL OR s.arms_length)
  AND MOD(ABS(HASHTEXT(s.county || ':' || s.source_parcel_id)::bigint),100) < :sample_percent
ORDER BY s.sale_date,s.id
""")


@dataclass(frozen=True)
class Split:
    train: pd.DataFrame
    validation: pd.DataFrame
    test: pd.DataFrame
    validation_start: pd.Timestamp
    test_start: pd.Timestamp
    evaluation_end: pd.Timestamp


def chronological_split(frame: pd.DataFrame, as_of: date | None = None) -> Split:
    dates = pd.to_datetime(frame["sale_date"], errors="coerce", utc=True).dt.tz_localize(None)
    frame = frame.assign(sale_date=dates).dropna(subset=["sale_date"]).sort_values("sale_date")
    end = pd.Timestamp(as_of or date.today())
    test_start = end - pd.DateOffset(days=365)
    validation_start = test_start - pd.DateOffset(days=365)
    return Split(frame[frame.sale_date < validation_start].copy(),
                 frame[(frame.sale_date >= validation_start) & (frame.sale_date < test_start)].copy(),
                 frame[(frame.sale_date >= test_start) & (frame.sale_date <= end)].copy(),
                 validation_start, test_start, end)


def prepare(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    input_rows = len(frame)
    frame = frame.copy()
    frame["sale_date"] = pd.to_datetime(frame["sale_date"], errors="coerce")
    frame["sale_year"] = frame.sale_date.dt.year
    frame["sale_month"] = frame.sale_date.dt.month
    if "prior_sale_date" not in frame:
        frame["prior_sale_date"] = pd.NaT
    if "prior_sale_price" not in frame:
        frame["prior_sale_price"] = np.nan
    if "snapshot_year" not in frame:
        frame["snapshot_year"] = np.nan
    frame["prior_sale_date"] = pd.to_datetime(frame["prior_sale_date"], errors="coerce")
    frame.loc[frame.prior_sale_date >= frame.sale_date, ["prior_sale_date", "prior_sale_price"]] = [pd.NaT, np.nan]
    frame["prior_sale_age_years"] = (frame.sale_date - frame.prior_sale_date).dt.days / 365.25
    frame["property_age"] = frame.sale_year - frame.year_built
    numeric = ["sale_price", *NUMERIC_FEATURES]
    for column in numeric:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    valid = (frame.sale_price.between(10_000, 50_000_000)
             & frame.sale_date.notna()
             & (frame.living_area.isna() | frame.living_area.between(100, 100_000))
             & (frame.year_built.isna() | frame.year_built.between(1600, frame.sale_year)))
    frame = frame.loc[valid].copy()
    for column in CATEGORICAL_FEATURES:
        frame[column] = frame[column].where(frame[column].notna() & frame[column].ne(""), np.nan)
    usable_features = [name for name in FEATURES if frame[name].notna().any()]
    return frame, {"input_rows": input_rows, "eligible_rows": len(frame),
                   "excluded_rows": input_rows - len(frame), "usable_features": usable_features,
                   "snapshot_rule": "most structurally complete snapshot strictly before sale year; latest year breaks ties",
                   "prior_sale_rule": "latest qualifying sale strictly before target sale date",
                   "pre_sale_snapshot_rows": int(frame.snapshot_year.notna().sum()),
                   "prior_sale_rows": int(frame.prior_sale_price.notna().sum())}


def residential_sales(frame: pd.DataFrame, state: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Limit candidate and holdouts to explicitly market-qualified residential sales."""
    sources = {"NY": {NY_SALESWEB}, "IL": {IL_COOK, IL_MYDEC}}[state]
    qualified = frame.loc[
        frame.sale_source_id.isin(sources) & frame.arms_length.eq(True)
        & frame.sale_price.between(25_000, 10_000_000)
    ].copy()
    qualified = qualified.loc[
        qualified.apply(lambda row: residential_scope(
            state, row.snapshot_source_id, row.land_use_code), axis=1)
    ]
    before_dedupe = len(qualified)
    qualified = qualified.sort_values("sale_id").drop_duplicates(
        ["county", "source_parcel_id", "sale_date", "sale_price"], keep="first")
    return qualified, {
        "segment": "residential", "source_ids": sorted(sources),
        "arms_length": "explicit true only", "price_range": [25_000, 10_000_000],
        "property_class": "NY ORPTS/SalesWeb 210-299; IL Cook 201-299 or MyDec B, from pre-sale snapshot",
        "segment_rows": len(qualified), "duplicate_sale_events_removed": before_dedupe - len(qualified),
    }


def regression_metrics(actual: Any, predicted: Any) -> dict[str, float]:
    actual = np.asarray(actual, dtype=float); predicted = np.asarray(predicted, dtype=float)
    errors = np.abs(actual - predicted); denominator = np.maximum(np.abs(actual), 1)
    return {"mae": round(float(mean_absolute_error(actual, predicted)), 2),
            "rmse": round(float(mean_squared_error(actual, predicted) ** .5), 2),
            "median_absolute_error": round(float(np.median(errors)), 2),
            "mape_percent": round(float(np.mean(errors / denominator) * 100), 2),
            "within_10_percent": round(float(np.mean(errors / denominator <= .10) * 100), 2),
            "within_20_percent": round(float(np.mean(errors / denominator <= .20) * 100), 2),
            "r2": round(float(r2_score(actual, predicted)), 4)}


def baseline(train: pd.DataFrame, target: pd.DataFrame) -> np.ndarray:
    county_medians = train.groupby("county", dropna=False).sale_price.median()
    state_median = float(train.sale_price.median())
    return target.county.map(county_medians).fillna(state_median).to_numpy(dtype=float)


def make_pipeline(numeric: list[str], categorical: list[str]) -> Pipeline:
    transformers = []
    if numeric:
        transformers.append(("numeric", SimpleImputer(strategy="median"), numeric))
    if categorical:
        transformers.append(("categorical", Pipeline([
            ("impute", SimpleImputer(strategy="most_frequent")),
            ("encode", OneHotEncoder(handle_unknown="ignore", min_frequency=5)),
        ]), categorical))
    return Pipeline([
        ("features", ColumnTransformer(transformers)),
        ("model", XGBRegressor(n_estimators=350, learning_rate=.05, max_depth=7,
                               min_child_weight=8, subsample=.85, colsample_bytree=.85,
                               objective="reg:absoluteerror", eval_metric="mae",
                               tree_method="hist", random_state=42, n_jobs=4)),
    ])


def predict_price(pipeline: Pipeline, frame: pd.DataFrame, features: list[str],
                  transform: str) -> np.ndarray:
    values = pipeline.predict(frame[features])
    return np.expm1(values) if transform == "log1p" else values


def feature_weightages(pipeline: Pipeline, validation: pd.DataFrame,
                       features: list[str], transform: str) -> dict[str, float]:
    """Relative validation MAE increase on shuffling each original feature.

    These are predictive reliance scores, not causal coefficients or dollar weights.
    """
    subset = validation.sample(min(len(validation), 1000), random_state=42)
    baseline_mae = mean_absolute_error(
        subset.sale_price, predict_price(pipeline, subset, features, transform))
    rng = np.random.default_rng(42)
    increases = {}
    for name in features:
        shuffled = subset.copy()
        shuffled[name] = rng.permutation(shuffled[name].to_numpy())
        mae = mean_absolute_error(subset.sale_price,
                                  predict_price(pipeline, shuffled, features, transform))
        increases[name] = max(0.0, float(mae - baseline_mae))
    total = sum(increases.values())
    return {name: round(value / total * 100, 2) if total else 0.0
            for name, value in sorted(increases.items(), key=lambda item: item[1], reverse=True)}


def passes_promotion_gate(metrics: dict[str, Any]) -> bool:
    model = metrics["test"]["xgboost"]
    baseline = metrics["test"]["prior_county_median"]
    return model["mae"] < baseline["mae"] and model["within_20_percent"] >= 50


def train_state(state: str, output_dir: Path, as_of: date | None = None,
                min_train: int = 1000, min_holdout: int = 250,
                sample_percent: int = 10, segment: str = "all") -> dict[str, Any]:
    if segment == "residential" and state not in {"NY", "IL"}:
        raise ValueError("Residential v2 is currently defined only for NY and IL")
    cutoff = min(as_of or date.today(), date.today())
    with warehouse_engine.connect() as connection:
        frame = pd.read_sql(TRAINING_SQL, connection, params={
            "state": state, "as_of": cutoff, "sample_percent": sample_percent})
    frame, audit = prepare(frame)
    if segment == "residential":
        frame, scope_audit = residential_sales(frame, state)
        audit.update(scope_audit)
    split = chronological_split(frame, cutoff)
    version = (f"{state.lower()}-xgb-residential-v2" if segment == "residential"
               else f"{state.lower()}-xgb-v1") + f"-{split.evaluation_end.date().isoformat()}-p{sample_percent}"
    report: dict[str, Any] = {
        "state": state, "segment": segment, "model_version": version, "target": "sale_price",
        "trained_at": datetime.now(UTC).isoformat(), "data_audit": audit,
        "sample_percent": sample_percent,
        "split": {"train": f"before {split.validation_start.date()}",
                  "validation": f"{split.validation_start.date()}..{(split.test_start - pd.DateOffset(days=1)).date()}",
                  "test": f"{split.test_start.date()}..{split.evaluation_end.date()}"},
        "rows": {"train": len(split.train), "validation": len(split.validation), "test": len(split.test)},
        "status": "INSUFFICIENT_DATA", "metrics": {},
    }
    if len(split.train) < min_train or min(len(split.validation), len(split.test)) < min_holdout:
        report["reason"] = f"requires >= {min_train} train and >= {min_holdout} rows in each holdout"
        save_report(output_dir, state, report, segment)
        record_run(report, None)
        return report
    usable = [name for name in FEATURES if split.train[name].notna().any()]
    report["features"] = usable
    report["feature_history"] = {
        name: {"pre_sale_snapshot": int(subset.snapshot_year.notna().sum()),
               "prior_sale": int(subset.prior_sale_price.notna().sum())}
        for name, subset in (("train", split.train), ("validation", split.validation), ("test", split.test))}
    if not any(name in usable for name in (
            "living_area", "bedrooms", "bathrooms", "year_built", "total_assessed_value",
            "zip_code", "prior_sale_price")):
        report["reason"] = "No property-level or prior-sale features available in the training period"
        save_report(output_dir, state, report, segment)
        record_run(report, None)
        return report
    numeric = [f for f in NUMERIC_FEATURES if f in usable]
    categorical = [f for f in CATEGORICAL_FEATURES if f in usable]
    candidates = []
    for target_transform in ("identity", "log1p"):
        pipeline = make_pipeline(numeric, categorical)
        target = split.train.sale_price if target_transform == "identity" else np.log1p(split.train.sale_price)
        pipeline.fit(split.train[usable], target)
        validation_prediction = predict_price(pipeline, split.validation, usable, target_transform)
        candidates.append((regression_metrics(split.validation.sale_price, validation_prediction)["mae"],
                           target_transform, pipeline))
    _, transform, selected = min(candidates, key=lambda candidate: candidate[0])
    for name, subset in (("validation", split.validation), ("test", split.test)):
        prediction = predict_price(selected, subset, usable, transform)
        report["metrics"][name] = {"xgboost": regression_metrics(subset.sale_price, prediction),
                                    "prior_county_median": regression_metrics(subset.sale_price, baseline(split.train, subset))}
    passed = passes_promotion_gate(report["metrics"])
    report.update(status="PROMOTED" if passed else "REJECTED", features=usable,
                  selected_target_transform=transform,
                  feature_weightages=feature_weightages(selected, split.validation, usable, transform),
                  feature_weightage_note="Relative validation MAE increase when shuffled; predictive, not causal",
                  promotion_gate={"rule": "test MAE beats county median and at least 50% of sales are within 20%",
                                  "passed": passed})
    report["metrics"]["feature_weightages"] = report["feature_weightages"]
    artifact = None
    if passed:
        production = clone(selected)
        all_rows = pd.concat([split.train, split.validation, split.test], ignore_index=True)
        production_target = all_rows.sale_price if transform == "identity" else np.log1p(all_rows.sale_price)
        production.fit(all_rows[usable], production_target)
        output_dir.mkdir(parents=True, exist_ok=True)
        artifact = output_dir / f"{version}.joblib"
        joblib.dump({"pipeline": production, "features": usable, "target_transform": transform,
                     "model_version": version, "segment": segment, "metrics": report["metrics"],
                     "test_start": split.test_start.date().isoformat(),
                     "data_as_of": split.evaluation_end.date().isoformat()}, artifact)
    save_report(output_dir, state, report, segment)
    record_run(report, artifact)
    return report


def save_report(output_dir: Path, state: str, report: dict[str, Any], segment: str = "all") -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = "_residential" if segment == "residential" else ""
    (output_dir / f"{state.lower()}{suffix}_avm_metrics.json").write_text(json.dumps(report, indent=2) + "\n")


def record_run(report: dict[str, Any], artifact: Path | None) -> None:
    with warehouse_engine.begin() as connection:
        connection.execute(text("""INSERT INTO state_avm_model_runs
          (state,model_version,status,artifact_path,feature_names,split_definition,row_counts,metrics,data_as_of)
          VALUES(:state,:version,:status,:artifact,CAST(:features AS JSONB),CAST(:split AS JSONB),
                 CAST(:rows AS JSONB),CAST(:metrics AS JSONB),:as_of)
          ON CONFLICT(state,model_version) DO UPDATE SET status=EXCLUDED.status,
          artifact_path=EXCLUDED.artifact_path,feature_names=EXCLUDED.feature_names,
          split_definition=EXCLUDED.split_definition,row_counts=EXCLUDED.row_counts,
          metrics=EXCLUDED.metrics,data_as_of=EXCLUDED.data_as_of,trained_at=NOW()"""),
          {"state": report["state"], "version": report["model_version"], "status": report["status"],
           "artifact": str(artifact) if artifact else None, "features": json.dumps(report.get("features", [])),
           "split": json.dumps(report["split"]), "rows": json.dumps(report["rows"]),
           "metrics": json.dumps(report["metrics"]), "as_of": report["split"]["test"].split("..")[-1]})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--states", nargs="+", choices=STATES, default=list(STATES))
    parser.add_argument("--as-of", type=date.fromisoformat)
    parser.add_argument("--output-dir", type=Path, default=MODEL_DIR)
    parser.add_argument("--min-train", type=int, default=1000)
    parser.add_argument("--min-holdout", type=int, default=250)
    parser.add_argument("--sample-percent", type=int, default=10,
                        help="Deterministic parcel sample percent (1-100); use 100 for all sales")
    parser.add_argument("--segment", choices=("all", "residential"), default="all")
    args = parser.parse_args()
    if not 1 <= args.sample_percent <= 100:
        parser.error("--sample-percent must be between 1 and 100")
    if args.segment == "residential" and any(state not in {"NY", "IL"} for state in args.states):
        parser.error("--segment residential supports NY and IL only")
    reports = []
    for state in args.states:
        try:
            report = train_state(state, args.output_dir, args.as_of, args.min_train,
                                 args.min_holdout, args.sample_percent, args.segment)
        except Exception as exc:
            report = {"state": state, "status": "FAILED", "error": str(exc)}
        reports.append(report)
        print(json.dumps(report, indent=2), flush=True)
    if any(report["status"] == "FAILED" for report in reports):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
