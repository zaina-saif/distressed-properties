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
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.frozen import FrozenEstimator
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder
from sqlalchemy import text

from app.database.session import engine

MODEL_VERSION = "sale_probability_gradient_boosting_v5"
MODEL_NAME = "sale_probability_gradient_boosting"
TARGET = "reaches_auction"
MODEL_DIR = Path(__file__).resolve().parents[1] / "models"
ARTIFACT_PATH = MODEL_DIR / f"{MODEL_VERSION}.joblib"
METRICS_PATH = MODEL_DIR / f"{MODEL_VERSION}_metrics.json"

POSITIVE_TERMINAL = (
    "sold", "purchased", "plaintiff_buy_back", "buy_back", "purchased_-_",
    # Ohio: auctioned with no bid at the opening price. The sale went to auction.
    "unsold",
)
NEGATIVE_TERMINAL = (
    "cancel", "settled", "redeem", "writ_expired", "withdraw", "dismiss",
    "closed", "expired", "bankrupt",
)


# States whose minimum bid is only set shortly before the sale (Indiana's sheriff
# fills it in near the date; it stays "Pending" before). Whether it is set shows
# how far a case got, not whether it will sell, so these use the judgment only.
UPSET_SET_LATE = {"IN"}


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
    # e.g. "sold_or_cancelled_unverified": the outcome is unknown, not a sale.
    if "unverified" in value:
        return None
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
    if str(sale.get("state") or "").upper() in UPSET_SET_LATE:
        upset = None
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
        # Earlier sale dates' results: Ohio re-offers a property after an
        # auction with no bids, and Florida resets cancelled sales.
        "cancelled_count": sum("cancel" in status for status in statuses),
        "unsold_count": sum(status == "unsold" for status in statuses),
        "prior_sold_count": sum(status.startswith(("sold", "purchased")) and "unverified" not in status
                                for status in statuses),
        "days_in_process": max(0, days_in_process),
        "days_since_previous_event": max(0, days_since_previous),
        "days_until_sale": days_until_sale,
        # Month of the scheduled date being predicted. The sale's final date
        # (current_sale_date) would reveal later adjournments during training.
        "sale_month": event_date.month if event_date else (sale_date.month if sale_date else 0),
        "sale_weekday": (event_date or sale_date).weekday() if (event_date or sale_date) else 0,
        "minimum_bid": minimum_bid,
        "has_upset_price": int(upset is not None),
    }


def build_training_rows(
    sales: list[dict[str, Any]],
    histories: dict[str, list[dict[str, Any]]],
    as_of: date | None = None,
) -> list[dict[str, Any]]:
    """Labeled scheduled events. With ``as_of``, only events whose sale date
    has passed are kept: before the date a sale can only have been cancelled,
    so unmatured events would bias the labels toward "no auction"."""
    rows: list[dict[str, Any]] = []
    for sale in sales:
        events = _sorted_events(histories.get(str(sale["id"]), []))
        schedule_indexes = [i for i, event in enumerate(events) if _is_scheduled(event)]
        if not schedule_indexes:
            rows.extend(_auction_result_rows(sale, events, as_of))
            continue
        for index in schedule_indexes:
            event_date = _as_date(events[index].get("sale_date"))
            if as_of is not None and (event_date is None or event_date >= as_of):
                continue
            prior = events[:index]
            outcome: int | None = None
            for later in events[index + 1:]:
                outcome = _terminal_label(later)
                if outcome is not None:
                    break
            if outcome is None:
                outcome = _terminal_label({"status": sale.get("current_status")})
            if outcome is None:
                continue
            row = build_features(sale, prior, event_date)
            row["label"] = outcome
            row["sale_id"] = str(sale["id"])
            row["event_date"] = event_date.isoformat() if event_date else None
            rows.append(row)
    return rows


def _auction_result_rows(sale: dict[str, Any], events: list[dict[str, Any]],
                         as_of: date | None) -> list[dict[str, Any]]:
    """Rows for a sale known only from published auction results (RealAuction's
    closed calendars for OH and FL): each dated outcome, such as "cancelled" on
    one date and "sold" on a later one, stands for a sale date with that result.
    Features use only the outcomes before it."""
    rows: list[dict[str, Any]] = []
    seen: set[tuple[date, int]] = set()
    for index, event in enumerate(events):
        event_date = _as_date(event.get("sale_date"))
        outcome = _terminal_label(event)
        if outcome is None or event_date is None or (as_of is not None and event_date >= as_of):
            continue
        if (event_date, outcome) in seen:
            continue
        seen.add((event_date, outcome))
        prior = [e for e in events[:index] if (_as_date(e.get("sale_date")) or date.min) < event_date]
        row = build_features(sale, prior, event_date)
        row["label"] = outcome
        row["sale_id"] = str(sale["id"])
        row["event_date"] = event_date.isoformat()
        rows.append(row)
    return rows


def _load_db_rows() -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    with engine.connect() as connection:
        sales = [dict(row) for row in connection.execute(text("""
            SELECT id,state,county,current_status,current_sale_date,upset_price,judgment_amount
            FROM sheriff_sales
            WHERE lower(current_status) NOT LIKE '%unverified%'
        """ )).mappings()]
        sales = [sale for sale in sales if _norm(sale.get("current_status")) == "scheduled"
                 or _terminal_label({"status": sale.get("current_status")}) is not None]
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


# days_until_sale is measured to the sale's final date, which during training
# reveals whether this scheduled date was later adjourned; for live sales it is
# always 0. Built for reference only, never trained on.
LEAKY_FEATURES = {"days_until_sale"}

DEFAULT_PARAMS = {"learning_rate": 0.05, "max_iter": 300, "max_leaf_nodes": 15, "min_samples_leaf": 40,
                  "l2_regularization": 1.0}
PARAM_GRID = [
    {"learning_rate": lr, "max_iter": 300, "max_leaf_nodes": leaves, "min_samples_leaf": leaf, "l2_regularization": 1.0}
    for lr in (0.03, 0.05) for leaves in (15, 31) for leaf in (20, 40, 80)
]
CATEGORICAL = ["state", "county"]
NUMERIC = [
    "prior_event_count", "prior_scheduled_count", "adjournment_count",
    "plaintiff_adjournment_count", "defendant_adjournment_count", "court_adjournment_count",
    "bankruptcy_count", "distinct_status_count", "cancelled_count", "unsold_count", "prior_sold_count",
    "days_in_process", "days_since_previous_event", "sale_month", "sale_weekday", "minimum_bid", "has_upset_price",
]


def _make_estimator(params: dict[str, Any] | None = None):
    # Histogram boosting splits on state and county natively, which beats
    # one-hot columns for the ~200 counties and trains in seconds on OH/FL history.
    preprocess = ColumnTransformer([
        ("categorical", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1,
                                       encoded_missing_value=-1), CATEGORICAL),
        ("numeric", "passthrough", NUMERIC),
    ])
    return Pipeline([
        ("preprocess", preprocess),
        ("classifier", HistGradientBoostingClassifier(
            categorical_features=list(range(len(CATEGORICAL))), random_state=42, **(params or DEFAULT_PARAMS))),
    ])


def train_model(rows: list[dict[str, Any]]) -> tuple[Any, dict[str, Any]]:
    if len(rows) < 30 or len({row["label"] for row in rows}) < 2:
        raise ValueError(f"Need at least 30 labeled events and both classes; got {len(rows)} rows")
    frame = pd.DataFrame(rows)
    feature_columns = [c for c in frame.columns if c not in {"label", "sale_id", "event_date"} | LEAKY_FEATURES]
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
    params, tuning = _select_params(train_frame, feature_columns)
    evaluated = _fit_time_calibrated(train_frame, feature_columns, params)
    probabilities = evaluated.predict_proba(test_frame[feature_columns])[:, 1]
    # The deployed model is refit the same way on every labeled event, so the
    # newest outcomes inform live scores; the metrics above describe the
    # evaluated model, which never saw the holdout.
    calibrated = _fit_time_calibrated(frame, feature_columns, params)
    by_state = {}
    for state, group in test_frame.assign(probability=probabilities).groupby("state"):
        if len(group) >= 50 and group["label"].nunique() == 2:
            by_state[state] = {"rows": int(len(group)), "roc_auc": round(float(roc_auc_score(group["label"], group["probability"])), 4),
                               "positive_rate": round(float(group["label"].mean()), 4),
                               "mean_prediction": round(float(group["probability"].mean()), 4)}
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
        "holdout_mean_prediction": round(float(probabilities.mean()), 4),
        "holdout_positive_rate": round(float(test_frame["label"].mean()), 4),
        "holdout_by_state": by_state,
        "calibration": "sigmoid, fit on the most recent 20% of events after fitting on the older 80%",
        "holdout_cutoff": cutoff.isoformat() if cutoff is not None else None,
        "feature_columns": feature_columns,
        "hyperparameters": params,
        "tuning": tuning,
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }
    return (calibrated, metrics)


def _time_split(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, Any]:
    dates = pd.to_datetime(frame["event_date"], errors="coerce")
    cutoff = dates.quantile(0.8) if dates.notna().any() else None
    recent = dates >= cutoff if cutoff is not None else pd.Series(False, index=frame.index)
    return frame.loc[~recent], frame.loc[recent], cutoff


def _fit_time_calibrated(frame: pd.DataFrame, feature_columns: list[str], params: dict[str, Any]):
    """Fit on older events and calibrate on the newest ones, so probabilities
    track the recent auction rate rather than the historical average."""
    older, recent, _ = _time_split(frame)
    if len(recent) < 30 or older["label"].nunique() < 2 or recent["label"].nunique() < 2:
        model = CalibratedClassifierCV(estimator=_make_estimator(params), method="sigmoid", cv=3)
        return model.fit(frame[feature_columns], frame["label"])
    base = _make_estimator(params).fit(older[feature_columns], older["label"])
    return CalibratedClassifierCV(FrozenEstimator(base), method="sigmoid").fit(recent[feature_columns], recent["label"])


def _select_params(train_frame: pd.DataFrame, feature_columns: list[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Pick hyperparameters on a time-ordered split of the training data only,
    so the final holdout stays untouched by model selection."""
    fit, valid, cutoff = _time_split(train_frame)
    if len(valid) < 30 or fit["label"].nunique() < 2 or valid["label"].nunique() < 2:
        return DEFAULT_PARAMS, {"skipped": "validation split too small"}
    results = []
    for params in PARAM_GRID:
        model = _make_estimator(params).fit(fit[feature_columns], fit["label"])
        probabilities = model.predict_proba(valid[feature_columns])[:, 1]
        results.append((round(float(roc_auc_score(valid["label"], probabilities)), 4), params))
    best_auc, best = max(results, key=lambda pair: pair[0])
    default_auc = next(auc for auc, params in results if params == DEFAULT_PARAMS)
    return best, {"validation_rows": int(len(valid)), "validation_cutoff": cutoff.isoformat(),
                  "best_validation_roc_auc": best_auc, "default_validation_roc_auc": default_auc}


# Inputs grouped the way a person would read them, for per-property reasons.
DRIVER_GROUPS: list[tuple[str, str, list[str]]] = [
    ("adjournments", "Adjournments", ["adjournment_count", "plaintiff_adjournment_count",
                                      "defendant_adjournment_count", "court_adjournment_count"]),
    ("bankruptcy", "Bankruptcy filings", ["bankruptcy_count"]),
    ("reschedules", "Times scheduled before", ["prior_scheduled_count", "prior_event_count", "distinct_status_count"]),
    ("days_in_process", "Time in the sale process", ["days_in_process"]),
    ("days_since_previous_event", "Days since the last status change", ["days_since_previous_event"]),
    ("prior_results", "Earlier sale dates", ["cancelled_count", "unsold_count", "prior_sold_count"]),
    ("sale_month", "Sale month", ["sale_month"]),
    ("sale_weekday", "Sale weekday", ["sale_weekday"]),
    ("minimum_bid", "Minimum bid", ["minimum_bid", "has_upset_price"]),
    ("county", "County", ["county"]),
]


def typical_values(frame: pd.DataFrame, feature_columns: list[str]) -> dict[str, Any]:
    """The 'typical' sale: median of each numeric input, most common category."""
    typical: dict[str, Any] = {}
    for column in feature_columns:
        series = frame[column]
        if pd.api.types.is_numeric_dtype(series):
            typical[column] = _json_safe(series.median())
        else:
            typical[column] = series.mode().iloc[0]
    return typical


def typical_by_state(frame: pd.DataFrame, feature_columns: list[str]) -> dict[str, dict[str, Any]]:
    """Typical sale per state, so a sale is explained against its own state
    (most common county and medians taken together); "ALL" covers the rest."""
    typical = {"ALL": typical_values(frame, feature_columns)}
    for state, group in frame.groupby("state"):
        if len(group) >= 50:
            typical[str(state)] = typical_values(group, feature_columns)
    return typical


def _describe(group: str, values: dict[str, Any]) -> str:
    def n(key: str) -> str:
        value = values.get(key)
        return "—" if value is None else f"{float(value):,.0f}"
    if group == "county":
        return str(values.get("county") or "—")
    if group == "adjournments":
        return f"{n('adjournment_count')} ({n('plaintiff_adjournment_count')} plaintiff, {n('defendant_adjournment_count')} defendant)"
    if group == "reschedules":
        return n("prior_scheduled_count")
    if group == "minimum_bid":
        return "Not published" if not values.get("minimum_bid") else f"${float(values['minimum_bid']):,.0f}"
    if group in {"days_in_process", "days_since_previous_event"}:
        return f"{n(group)} days"
    if group == "prior_results":
        parts = [f"{n(key)} {word}" for key, word in (("cancelled_count", "cancelled"), ("unsold_count", "with no bids"),
                                                       ("prior_sold_count", "sold")) if values.get(key)]
        return ", ".join(parts) if parts else "None"
    if group == "sale_weekday":
        day = values.get("sale_weekday")
        return datetime(2024, 1, 1 + int(day)).strftime("%A") if day is not None else "—"
    if group == "sale_month":
        month = values.get("sale_month")
        return datetime(2000, int(month), 1).strftime("%B") if month else "—"
    return n(DRIVER_GROUPS_BY_KEY[group][0])


DRIVER_GROUPS_BY_KEY = {key: columns for key, _, columns in DRIVER_GROUPS}


def explain_drivers(model: Any, frame: pd.DataFrame, feature_columns: list[str],
                    typical: dict[str, Any], top: int = 4) -> list[list[dict[str, Any]]]:
    """For each row, how many points each group of inputs moves the estimate
    compared with a typical value: probability minus the probability with that
    group set to typical. Returns the largest effects per row."""
    base = model.predict_proba(frame[feature_columns])[:, 1]
    impacts: dict[str, np.ndarray] = {}
    for key, _, columns in DRIVER_GROUPS:
        present = [column for column in columns if column in feature_columns]
        if not present:
            continue
        changed = frame[feature_columns].copy()
        for column in present:
            changed[column] = typical[column]
        impacts[key] = base - model.predict_proba(changed)[:, 1]
    labels = {key: label for key, label, _ in DRIVER_GROUPS}
    results = []
    for index in range(len(frame)):
        values = frame.iloc[index].to_dict()
        ranked = sorted(impacts, key=lambda key: abs(impacts[key][index]), reverse=True)
        results.append([
            {"key": key, "label": labels[key], "value": _describe(key, values),
             "typical": _describe(key, typical), "impact": round(float(impacts[key][index]), 4)}
            for key in ranked[:top] if abs(impacts[key][index]) >= 0.005
        ])
    return results


def _json_safe(value: Any) -> Any:
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _without_state_history(model: Any, frame: pd.DataFrame, feature_columns: list[str],
                           by_state: dict[str, dict[str, Any]]) -> np.ndarray:
    """Estimate for sales in a state the model has no results from: the average
    of its estimates as if the sale were in each known state's typical county,
    rather than whatever the trees do with an unseen state."""
    estimates = []
    for state, values in by_state.items():
        if state == "ALL":
            continue
        moved = frame[feature_columns].copy()
        moved["state"] = state
        moved["county"] = values["county"]
        estimates.append(model.predict_proba(moved)[:, 1])
    return np.mean(estimates, axis=0)


def score_current(model: Any, sales: list[dict[str, Any]], histories: dict[str, list[dict[str, Any]]],
                  feature_columns: list[str], typical: dict[str, Any] | None = None,
                  metrics: dict[str, Any] | None = None) -> int:
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
    drivers: list[list[dict[str, Any]]] = [[] for _ in rows]
    # Older artifacts hold one typical sale; newer ones hold one per state with enough history.
    by_state = (typical if "ALL" in typical else {"ALL": typical}) if typical else {}
    trained_states = {state for state in by_state if state != "ALL"}
    untrained = frame["state"].map(lambda state: bool(trained_states) and state not in trained_states).to_numpy()
    if untrained.any():
        probabilities[untrained] = _without_state_history(model, frame[untrained], feature_columns, by_state)
    if typical:
        for state, group in frame[~untrained].groupby("state"):
            state_typical = by_state.get(str(state), by_state["ALL"])
            for position, row_drivers in zip(group.index, explain_drivers(
                    model, group.reset_index(drop=True), feature_columns, state_typical)):
                drivers[position] = row_drivers
    now_dt = datetime.now(timezone.utc)
    with engine.begin() as connection:
        for (sale, feature_row), probability, row_drivers in zip(rows, probabilities, drivers):
            features = {key: _json_safe(value) for key, value in feature_row.items()}
            no_history = feature_row["state"] not in trained_states and bool(trained_states)
            explanations = {
                "methodology": (
                    "Calibrated gradient boosting trained on past sale dates in NJ, OH, FL and IN that have already "
                    "passed, including published auction results, using only the history known before each date."
                ),
                "target": "Next scheduled event reaches a sold/purchased terminal outcome",
                "model_version": MODEL_VERSION,
                "drivers": row_drivers,
                # No past results from this state yet: the estimate averages the states the model knows.
                "state_without_history": no_history,
                "trained_states": sorted(trained_states),
                "drivers_method": "Points this input moves the estimate compared with a typical sale in its state.",
                "model_quality": {key: (metrics or {}).get(key) for key in (
                    "holdout_rows", "holdout_roc_auc", "holdout_brier_score",
                    "holdout_mean_prediction", "holdout_positive_rate", "holdout_cutoff", "holdout_by_state")},
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
        count = score_current(artifact["model"], sales, histories, artifact["feature_columns"], artifact.get("typical"),
                              artifact.get("metrics"))
        print(f"Scored {count} current scheduled sales with {MODEL_VERSION}")
        return
    rows = build_training_rows(sales, histories, as_of=datetime.now(timezone.utc).date())
    model, metrics = train_model(rows)
    feature_columns = metrics["feature_columns"]
    typical = typical_by_state(pd.DataFrame(rows)[feature_columns].fillna(0), feature_columns)
    metrics["typical_sale"] = typical
    joblib.dump({"model": model, "feature_columns": feature_columns, "metrics": metrics, "typical": typical}, ARTIFACT_PATH)
    METRICS_PATH.write_text(json.dumps(metrics, indent=2, default=str) + "\n")
    count = score_current(model, sales, histories, feature_columns, typical, metrics)
    print(json.dumps({"trained": metrics, "scored_current": count}, indent=2))


if __name__ == "__main__":
    main()
