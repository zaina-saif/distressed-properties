"""Train a leakage-aware Monmouth residential automated valuation model."""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.neighbors import BallTree
from sqlalchemy import text
from xgboost import XGBRegressor

from app.database.session import engine

BACKEND = Path(__file__).resolve().parents[1]
MODEL_DIR = BACKEND / "data" / "nj_property" / "models"
NUMERIC_FEATURES = [
    "acreage", "year_built", "living_space", "land_assessed",
    "improvement_assessed", "total_assessed", "annual_property_tax",
    "sale_month", "property_age",
    "local_comp_median_price", "local_comp_median_ppsf",
    "local_comp_median_miles", "local_comp_count",
]
CATEGORICAL_FEATURES = [
    "municipality_code", "building_class", "zoning", "property_use_code", "census_tract",
]
QUERY = """
SELECT sale_year, municipality_code, block, lot, deed_date, sale_price, acreage, zoning,
       building_class, year_built, living_space, land_assessed,
       improvement_assessed, total_assessed, annual_property_tax,
       census_tract, property_use_code, latitude, longitude
FROM nj_avm_training_sales
ORDER BY deed_date, id
"""

def metrics(actual, predicted) -> dict[str, float]:
    actual, predicted = np.asarray(actual), np.asarray(predicted)
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

def prepare(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    input_rows = len(frame)
    frame["deed_date"] = pd.to_datetime(frame["deed_date"], errors="coerce")
    frame["sale_month"] = frame["deed_date"].dt.month
    frame["property_age"] = frame["sale_year"] - frame["year_built"]
    rules = (
        frame["deed_date"].notna()
        & frame["sale_price"].between(25_000, 5_000_000)
        & frame["living_space"].between(300, 10_000)
        & frame["total_assessed"].gt(0)
        & (frame["year_built"].isna() | frame["year_built"].between(1700, frame["sale_year"] + 1))
        & (frame["acreage"].isna() | frame["acreage"].between(0.01, 25))
    )
    clean = frame.loc[rules].copy().sort_values(["deed_date", "municipality_code", "sale_price"])
    clean = add_comparable_features(clean)
    clean = add_distance_comparable_features(clean)
    audit = {
        "input_rows": input_rows, "eligible_rows": len(clean), "excluded_rows": input_rows-len(clean),
        "rules": {"sale_price":"25000..5000000", "living_space":"300..10000",
                  "total_assessed":">0", "year_built":"1700..sale_year+1 or missing",
                  "acreage":"0.01..25 or missing", "deed_date":"required"},
    }
    return clean, audit

def add_comparable_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Add features using only completed quarters and strictly earlier parcel sales."""
    frame = frame.copy()
    frame["quarter"] = frame["deed_date"].dt.to_period("Q")
    frame["price_per_sqft"] = frame["sale_price"] / frame["living_space"]

    municipality = (frame.groupby(["municipality_code", "quarter"], observed=True)
        .agg(median_price=("sale_price", "median"), median_ppsf=("price_per_sqft", "median"))
        .sort_index())
    municipality["municipality_prior_quarter_median_price"] = municipality.groupby(level=0)["median_price"].shift(1)
    municipality["municipality_prior_quarter_median_ppsf"] = municipality.groupby(level=0)["median_ppsf"].shift(1)
    municipality["municipality_trailing_4q_median_price"] = (municipality.groupby(level=0)["median_price"]
        .transform(lambda values: values.shift(1).rolling(4, min_periods=1).median()))
    municipality["municipality_trailing_4q_median_ppsf"] = (municipality.groupby(level=0)["median_ppsf"]
        .transform(lambda values: values.shift(1).rolling(4, min_periods=1).median()))
    frame = frame.merge(municipality.drop(columns=["median_price", "median_ppsf"]),
        left_on=["municipality_code", "quarter"], right_index=True, how="left")

    tract = (frame.groupby(["census_tract", "quarter"], observed=True)["sale_price"].median()
        .rename("tract_quarter_price").to_frame().sort_index())
    tract["tract_prior_quarter_median_price"] = tract.groupby(level=0)["tract_quarter_price"].shift(1)
    frame = frame.merge(tract[["tract_prior_quarter_median_price"]],
        left_on=["census_tract", "quarter"], right_index=True, how="left")

    parcel_key = ["municipality_code", "block", "lot"]
    frame = frame.sort_values(parcel_key + ["deed_date"])
    frame["prior_parcel_sale_price"] = frame.groupby(parcel_key, dropna=False)["sale_price"].shift(1)
    prior_date = frame.groupby(parcel_key, dropna=False)["deed_date"].shift(1)
    frame["months_since_prior_sale"] = (frame["deed_date"] - prior_date).dt.days / 30.4375
    return frame.sort_values("deed_date")

def add_distance_comparable_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Summarize earlier-quarter sales within five miles; never use current-quarter sales."""
    frame=frame.copy(); frame["quarter"]=frame["deed_date"].dt.to_period("Q")
    for column in ("local_comp_median_price","local_comp_median_ppsf","local_comp_median_miles"):
        frame[column]=np.nan
    frame["local_comp_count"]=0.0
    earth_miles=3958.7613
    for quarter in sorted(frame["quarter"].dropna().unique()):
        start=quarter.start_time; earliest=(quarter-8).start_time
        history=frame[(frame.deed_date < start)&(frame.deed_date >= earliest)&frame.latitude.notna()&frame.longitude.notna()]
        targets=frame[(frame.quarter == quarter)&frame.latitude.notna()&frame.longitude.notna()]
        if history.empty or targets.empty: continue
        tree=BallTree(np.radians(history[["latitude","longitude"]].to_numpy()),metric="haversine")
        k=min(20,len(history)); distances,indices=tree.query(
            np.radians(targets[["latitude","longitude"]].to_numpy()),k=k)
        history_prices=history.sale_price.to_numpy(); history_sqft=history.living_space.to_numpy()
        for row_position,target_index in enumerate(targets.index):
            miles=distances[row_position]*earth_miles; valid=miles <= 5
            if not valid.any(): continue
            selected=indices[row_position][valid]; prices=history_prices[selected]
            ppsf=prices/history_sqft[selected]
            frame.loc[target_index,["local_comp_median_price","local_comp_median_ppsf",
                "local_comp_median_miles","local_comp_count"]]=[
                np.median(prices),np.median(ppsf),np.median(miles[valid]),len(selected)]
    return frame

def train(output_dir: Path) -> dict:
    with engine.connect() as connection:
        frame = pd.read_sql(text(QUERY), connection)
    frame, audit = prepare(frame)
    train_df = frame[frame.sale_year <= 2024]
    validation_df = frame[frame.sale_year == 2025]
    test_df = frame[frame.sale_year == 2026]
    if min(map(len, (train_df, validation_df, test_df))) == 0:
        raise RuntimeError("Chronological split produced an empty partition")
    transformer = ColumnTransformer([
        ("numeric", Pipeline([("impute", SimpleImputer(strategy="median"))]), NUMERIC_FEATURES),
        ("categorical", Pipeline([("impute", SimpleImputer(strategy="most_frequent")),
            ("onehot", OneHotEncoder(handle_unknown="ignore"))]), CATEGORICAL_FEATURES),
    ])
    model = XGBRegressor(n_estimators=700, learning_rate=.035, max_depth=7,
        min_child_weight=5, subsample=.85, colsample_bytree=.85,
        objective="reg:absoluteerror", eval_metric="mae", random_state=42, n_jobs=-1)
    pipeline = Pipeline([("features", transformer), ("model", model)])
    features = NUMERIC_FEATURES + CATEGORICAL_FEATURES
    pipeline.fit(train_df[features], train_df.sale_price)
    report = {"trained_at":datetime.now(UTC).isoformat(), "model":"XGBRegressor",
        "target":"sale_price", "split":{"train":"2020-2024", "validation":"2025", "test":"2026"},
        "rows":{"train":len(train_df),"validation":len(validation_df),"test":len(test_df)},
        "data_audit":audit, "features":features, "metrics":{}}
    for name, subset in (("validation",validation_df),("test",test_df)):
        prediction = pipeline.predict(subset[features])
        assessed = subset.total_assessed.to_numpy()
        report["metrics"][name] = {"xgboost":metrics(subset.sale_price,prediction),
            "total_assessed_baseline":metrics(subset.sale_price,assessed)}
    output_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipeline, output_dir/"monmouth_avm_xgboost.joblib")
    (output_dir/"monmouth_avm_metrics.json").write_text(json.dumps(report,indent=2)+"\n")
    return report

def main() -> None:
    parser=argparse.ArgumentParser(); parser.add_argument("--output-dir",type=Path,default=MODEL_DIR)
    args=parser.parse_args(); print(json.dumps(train(args.output_dir),indent=2))

if __name__ == "__main__": main()
