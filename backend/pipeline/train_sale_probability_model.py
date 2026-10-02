"""Train and persist the sheriff-sale outcome model.

The training unit is a scheduled status event.  Features are calculated from
the history strictly before that event; the label is the first terminal event
after it.  Current scheduled sales are scored from the same feature builder
without a label.
"""

from __future__ import annotations

import argparse
import json
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from sqlalchemy import text

from app.database.session import engine

MODEL_VERSION = "sale_probability_gradient_boosting_v1"
MODEL_NAME = "sale_probability_gradient_boosting"
TARGET = "reaches_auction"
MODEL_DIR = Path(__file__).resolve().parents[1] / "models"
ARTIFACT_PATH = MODEL_DIR / f"{MODEL_VERSION}.joblib"
METRICS_PATH = MODEL_DIR / f"{MODEL_VERSION}_metrics.json"

POSITIVE_TERMINAL = (
    "sold", "purchased", "plaintiff_buy_back", "buy_back", "purchased_-_",
)
NEGATIVE_TERMINAL = (
    "cancel", "settled", "redeem", "writ_expired", "withdraw", "dismiss",
    "closed", "expired", "bankrupt",
)


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return pd.Timestamp(value).date()
    except (TypeError, ValueError):
        return None


def _is_scheduled(event: dict[str, Any]) -> bool:
    status = _norm(event.get("status"))
    raw = _norm(event.get("raw_status"))
    return status == "scheduled" or "scheduled" in raw or "rescheduled" in raw or "re_scheduled" in raw


def _terminal_label(event: dict[str, Any]) -> int | None:
    value = f"{_norm(event.get('status'))} {_norm(event.get('raw_status'))}"
    if any(token in value for token in POSITIVE_TERMINAL):
        return 1
    if any(token in value for token in NEGATIVE_TERMINAL):
        return 0
    return None


def _sorted_events(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(events, key=lambda e: (_as_date(e.get("sale_date")) or date.min, str(e.get("id") or "")))


def build_features(sale: dict[str, Any], prior_events: list[dict[str, Any]], event_date: date | None) -> dict[str, Any]:
    """Build leakage-safe, JSON-friendly features from prior history."""
    prior = _sorted_events(prior_events)
    raws = [_norm(e.get("raw_status") or e.get("status")) for e in prior]
    statuses = [_norm(e.get("status")) for e in prior]
    dates = [d for d in (_as_date(e.get("sale_date")) for e in prior) if d]
    adj = sum("adjourn" in raw for raw in raws)
    plaintiff = sum("plaintiff" in raw and "adjourn" in raw for raw in raws)
    defendant = sum("defendant" in raw and "adjourn" in raw for raw in raws)
    court = sum("court" in raw and "adjourn" in raw for raw in raws)
    bankruptcy = sum("bankrupt" in raw or "bankrupt" in status for raw, status in zip(raws, statuses))
    first_date = min(dates) if dates else event_date
    days_in_process = (event_date - first_date).days if event_date and first_date else 0
    previous_date = max(dates) if dates else None
    days_since_previous = (event_date - previous_date).days if event_date and previous_date else 0
    sale_date = _as_date(sale.get("current_sale_date"))
    days_until_sale = (sale_date - event_date).days if sale_date and event_date else 0
    upset = sale.get("upset_price")
    judgment = sale.get("judgment_amount")
    try:
        minimum_bid = float(upset if upset is not None else judgment) if (upset is not None or judgment is not None) else 0.0
    except (TypeError, ValueError):
        minimum_bid = 0.0
    return {
        "state": str(sale.get("state") or "").upper(),
        "county": str(sale.get("county") or "").strip() or "Unknown",
        "prior_event_count": len(prior),
        "prior_scheduled_count": sum(_is_scheduled(e) for e in prior),
        "adjournment_count": adj,
        "plaintiff_adjournment_count": plaintiff,
        "defendant_adjournment_count": defendant,
        "court_adjournment_count": court,
        "bankruptcy_count": bankruptcy,
        "distinct_status_count": len(set(statuses)),
        "days_in_process": max(0, days_in_process),
        "days_since_previous_event": max(0, days_since_previous),
        "days_until_sale": days_until_sale,
        "sale_month": sale_date.month if sale_date else (event_date.month if event_date else 0),
        "minimum_bid": minimum_bid,
        "has_upset_price": int(upset is not None),
    }


def build_training_rows(sales: list[dict[str, Any]], histories: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sale in sales:
        events = _sorted_events(histories.get(str(sale["id"]), []))
        schedule_indexes = [i for i, event in enumerate(events) if _is_scheduled(event)]
        for index in schedule_indexes:
            event_date = _as_date(events[index].get("sale_date"))
            prior = events[:index]
            outcome: int | None = None
            for later in events[index + 1:]:
                outcome = _terminal_label(later)
                if outcome is not None:
                    break
            if outcome is None:
                current = _norm(sale.get("current_status"))
                if current in {"sold", "cancelled"}:
                    outcome = 1 if current == "sold" else 0
            if outcome is None:
                continue
            row = build_features(sale, prior, event_date)
            row["label"] = outcome
            row["sale_id"] = str(sale["id"])
            row["event_date"] = event_date.isoformat() if event_date else None
            rows.append(row)
    return rows


def _load_db_rows() -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    with engine.connect() as connection:
        sales = [dict(row) for row in connection.execute(text("""
            SELECT id,state,county,current_status,current_sale_date,upset_price,judgment_amount
            FROM sheriff_sales
            WHERE lower(current_status) IN ('sold','cancelled','scheduled')
        """ )).mappings()]
        history_rows = connection.execute(text("""
            SELECT id,sheriff_sale_id,status,raw_status,sale_date,observed_at
            FROM sheriff_sale_status_history
            ORDER BY sale_date NULLS LAST, observed_at, id
        """)).mappings()
        histories: dict[str, list[dict[str, Any]]] = {}
        for row in history_rows:
            item = dict(row)
            histories.setdefault(str(item["sheriff_sale_id"]), []).append(item)
    return sales, histories


def _make_estimator():
    categorical = ["state", "county"]
    numeric = [
        "prior_event_count", "prior_scheduled_count", "adjournment_count",
        "plaintiff_adjournment_count", "defendant_adjournment_count", "court_adjournment_count",
        "bankruptcy_count", "distinct_status_count", "days_in_process",
        "days_since_previous_event", "days_until_sale", "sale_month", "minimum_bid", "has_upset_price",
    ]
    preprocess = ColumnTransformer([
        ("categorical", OneHotEncoder(handle_unknown="ignore", sparse_output=False), categorical),
        ("numeric", "passthrough", numeric),
    ])
    base = Pipeline([
        ("preprocess", preprocess),
        ("classifier", GradientBoostingClassifier(
            n_estimators=120, learning_rate=0.04, max_depth=2,
            min_samples_leaf=8, random_state=42,
        )),
    ])
    return base


def train_model(rows: list[dict[str, Any]]) -> tuple[Any, dict[str, Any]]:
    if len(rows) < 30 or len({row["label"] for row in rows}) < 2:
        raise ValueError(f"Need at least 30 labeled events and both classes; got {len(rows)} rows")
    frame = pd.DataFrame(rows)
    feature_columns = [c for c in frame.columns if c not in {"label", "sale_id", "event_date"}]
    frame[feature_columns] = frame[feature_columns].fillna(0)
    # Keep events from the latest 20% of dates out of fitting for a time-aware check.
    dates = pd.to_datetime(frame["event_date"], errors="coerce")
    cutoff = dates.quantile(0.8) if dates.notna().any() else None
    test_mask = dates >= cutoff if cutoff is not None else pd.Series(False, index=frame.index)
    if test_mask.sum() < 10 or frame.loc[test_mask, "label"].nunique() < 2 or frame.loc[~test_mask, "label"].nunique() < 2:
        train_idx, test_idx = train_test_split(np.arange(len(frame)), test_size=0.2, random_state=42, stratify=frame["label"])
        test_mask = pd.Series(False, index=frame.index)
        test_mask.iloc[test_idx] = True
    train_frame = frame.loc[~test_mask]
    test_frame = frame.loc[test_mask]
    estimator = _make_estimator()
    calibrated = CalibratedClassifierCV(estimator=estimator, method="sigmoid", cv=3)
    calibrated.fit(train_frame[feature_columns], train_frame["label"])
    probabilities = calibrated.predict_proba(test_frame[feature_columns])[:, 1]
    metrics = {
        "model_version": MODEL_VERSION,
        "model_name": MODEL_NAME,
        "target": TARGET,
        "training_rows": int(len(train_frame)),
        "holdout_rows": int(len(test_frame)),
        "positive_rows": int(frame["label"].sum()),
        "negative_rows": int((1 - frame["label"]).sum()),
        "holdout_roc_auc": round(float(roc_auc_score(test_frame["label"], probabilities)), 4),
        "holdout_pr_auc": round(float(average_precision_score(test_frame["label"], probabilities)), 4),
        "holdout_brier_score": round(float(brier_score_loss(test_frame["label"], probabilities)), 4),
        "holdout_cutoff": cutoff.isoformat() if cutoff is not None else None,
        "feature_columns": feature_columns,
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }
    return (calibrated, metrics)


def _json_safe(value: Any) -> Any:
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def score_current(model: Any, sales: list[dict[str, Any]], histories: dict[str, list[dict[str, Any]]], feature_columns: list[str]) -> int:
    current = [sale for sale in sales if _norm(sale.get("current_status")) == "scheduled"]
    now = datetime.now(timezone.utc).date()
    rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for sale in current:
        events = _sorted_events(histories.get(str(sale["id"]), []))
        sale_date = _as_date(sale.get("current_sale_date")) or now
        # The current scheduled event is the latest scheduled history at or before the sale date.
        scheduled = [(i, _as_date(e.get("sale_date"))) for i, e in enumerate(events) if _is_scheduled(e)]
        chosen = max((pair for pair in scheduled if pair[1] is None or pair[1] <= sale_date), key=lambda pair: pair[1] or date.min, default=None)
        prior = events[:chosen[0]] if chosen else [e for e in events if (_as_date(e.get("sale_date")) or date.min) < sale_date]
        rows.append((sale, build_features(sale, prior, chosen[1] if chosen else sale_date)))
    if not rows:
        return 0
    frame = pd.DataFrame([row for _, row in rows])[feature_columns].fillna(0)
    probabilities = model.predict_proba(frame)[:, 1]
    now_dt = datetime.now(timezone.utc)
    with engine.begin() as connection:
        for (sale, feature_row), probability in zip(rows, probabilities):
            features = {key: _json_safe(value) for key, value in feature_row.items()}
            explanations = {
                "methodology": "Calibrated gradient boosting trained on prior status history; current event features exclude later statuses.",
                "target": "Next scheduled event reaches a sold/purchased terminal outcome",
                "model_version": MODEL_VERSION,
            }
            connection.execute(text("""
                INSERT INTO sale_predictions(
                    id,sheriff_sale_id,prediction_target,probability,predicted_class,model_name,
                    model_version,feature_values,feature_explanations,predicted_at)
                VALUES(:id,:sale_id,:target,:probability,:predicted_class,:model_name,
                    :version,CAST(:features AS JSONB),CAST(:explanations AS JSONB),:predicted_at)
                ON CONFLICT (sheriff_sale_id,prediction_target,model_version)
                DO UPDATE SET probability=EXCLUDED.probability,
                    predicted_class=EXCLUDED.predicted_class,
                    model_name=EXCLUDED.model_name,
                    feature_values=EXCLUDED.feature_values,
                    feature_explanations=EXCLUDED.feature_explanations,
                    predicted_at=EXCLUDED.predicted_at
            """), {
                "id": str(uuid.uuid4()), "sale_id": sale["id"], "target": TARGET,
                "probability": round(float(probability), 6), "predicted_class": bool(probability >= 0.5),
                "model_name": MODEL_NAME, "version": MODEL_VERSION,
                "features": json.dumps(features), "explanations": json.dumps(explanations), "predicted_at": now_dt,
            })
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--score-only", action="store_true", help="Reuse the saved artifact and score current scheduled sales")
    args = parser.parse_args()
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    sales, histories = _load_db_rows()
    if args.score_only and ARTIFACT_PATH.exists():
        artifact = joblib.load(ARTIFACT_PATH)
        count = score_current(artifact["model"], sales, histories, artifact["feature_columns"])
        print(f"Scored {count} current scheduled sales with {MODEL_VERSION}")
        return
    rows = build_training_rows(sales, histories)
    model, metrics = train_model(rows)
    feature_columns = metrics["feature_columns"]
    joblib.dump({"model": model, "feature_columns": feature_columns, "metrics": metrics}, ARTIFACT_PATH)
    METRICS_PATH.write_text(json.dumps(metrics, indent=2) + "\n")
    count = score_current(model, sales, histories, feature_columns)
    print(json.dumps({"trained": metrics, "scored_current": count}, indent=2))


if __name__ == "__main__":
    main()
