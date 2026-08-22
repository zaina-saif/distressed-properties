"""Publish experimental Monroe KIZ AVM estimates for authoritatively matched sales."""
from __future__ import annotations

import argparse
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sqlalchemy import text

from pipeline.train_monroe_avm import CATEGORICAL_FEATURES, MODEL_DIR, NUMERIC_FEATURES


PROVIDER = "monroe_kiz_xgboost_avm_v1"
MODEL = MODEL_DIR / "monroe_kiz_avm_xgboost.joblib"
METRICS = MODEL_DIR / "monroe_kiz_avm_metrics.json"


def subjects() -> list[dict]:
    from app.database.session import engine
    query = text("""SELECT DISTINCT ON (p.id) p.id AS property_id,d.acreage,d.assessed_value,
      d.land_value,d.improvement_value,parcel.latitude,parcel.longitude,d.property_type,
      d.land_use_code,m.match_method,s.sheriff_number
      FROM sheriff_sales s JOIN properties p ON p.id=s.property_id
      JOIN pa_sheriff_sale_parcel_matches m ON m.sheriff_sale_id=s.id
      JOIN pa_parcels parcel ON parcel.id=m.parcel_id
      JOIN pa_property_details d ON d.parcel_id=parcel.id
      WHERE s.state='PA' AND s.county='Monroe' AND s.current_sale_date>=CURRENT_DATE
      ORDER BY p.id,s.current_sale_date""")
    with engine.connect() as connection:
        return [dict(row) for row in connection.execute(query).mappings()]


def feature_frame(rows: list[dict], effective_date: date | None = None) -> pd.DataFrame:
    effective_date = effective_date or date.today()
    return pd.DataFrame([
        {**row, "sale_year": effective_date.year, "sale_month": effective_date.month}
        for row in rows
    ])


def save(rows: list[dict], predictions: np.ndarray, interval: float, metrics_payload: dict) -> int:
    from app.database.session import engine
    insert = text("""INSERT INTO property_valuations(id,property_id,provider,estimated_value,
      low_value,high_value,confidence_score,provider_response,effective_date,retrieved_at,
      expires_at,is_current) VALUES(:id,:property_id,:provider,:estimate,:low,:high,:confidence,
      CAST(:response AS JSONB),CURRENT_DATE,NOW(),:expires,:is_current)""")
    saved = 0
    with engine.begin() as connection:
        for row, prediction in zip(rows, predictions):
            stronger = connection.execute(text("""SELECT EXISTS(SELECT 1 FROM property_valuations
              WHERE property_id=:property_id AND is_current AND provider<>:provider)"""),
              {"property_id": row["property_id"], "provider": PROVIDER}).scalar()
            connection.execute(text("""UPDATE property_valuations SET is_current=FALSE
              WHERE property_id=:property_id AND provider=:provider AND is_current"""),
              {"property_id": row["property_id"], "provider": PROVIDER})
            estimate = max(float(prediction), 25_000)
            response = {
                "model_status": metrics_payload["model_status"],
                "model_version": "monroe-kiz-v1-log-target",
                "source": metrics_payload["source"],
                "training_data_as_of": "2022-07-26",
                "identity_match_method": row["match_method"],
                "test_mae": interval,
                "test_mape_percent": metrics_payload["metrics"]["test"]
                    [metrics_payload["selected_candidate"]]["mape_percent"],
                "warning": "Experimental KIZ-subset statistical estimate; not an appraisal.",
            }
            connection.execute(insert, {
                "id": str(uuid.uuid4()), "property_id": row["property_id"],
                "provider": PROVIDER, "estimate": round(estimate, 2),
                "low": round(max(estimate - interval, 25_000), 2),
                "high": round(estimate + interval, 2), "confidence": 0.25,
                "response": json.dumps(response),
                "expires": datetime.now(timezone.utc) + timedelta(days=30),
                "is_current": not stronger,
            })
            saved += 1
    return saved


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()
    rows = subjects()
    if not rows:
        print("Scoreable Monroe properties: 0")
        return
    artifact = joblib.load(MODEL)
    metrics_payload = json.loads(METRICS.read_text())
    frame = feature_frame(rows)
    predictions = artifact["pipeline"].predict(frame[NUMERIC_FEATURES + CATEGORICAL_FEATURES])
    if artifact.get("target_transform") == "log1p":
        predictions = np.expm1(predictions)
    selected = metrics_payload["selected_candidate"]
    interval = float(metrics_payload["metrics"]["test"][selected]["mae"])
    print(f"Scoreable Monroe properties: {len(rows)}; median estimate: ${np.median(predictions):,.0f}")
    if args.save:
        print(f"Experimental Monroe valuations saved: {save(rows, predictions, interval, metrics_payload)}")


if __name__ == "__main__":
    main()
