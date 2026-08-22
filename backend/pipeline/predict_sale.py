"""Estimate whether a currently scheduled property will reach auction.

This is an explainable heuristic, not a statistically calibrated probability model.
It can be replaced once enough terminal sold/not-sold outcomes have been collected.
"""
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import text

MODEL_VERSION = "status_history_heuristic_v1"


@dataclass(frozen=True)
class StatusEvent:
    status: str
    raw_status: str
    sale_date: datetime | None


def _event_counts(events: list[StatusEvent]) -> dict[str, int]:
    unique: set[tuple[str, str, str | None]] = set()
    for event in events:
        status = (event.status or "").lower()
        raw = (event.raw_status or status).lower()
        date_key = event.sale_date.date().isoformat() if event.sale_date else None
        unique.add((status, raw, date_key))

    plaintiff = sum("adjourn" in raw and "plaintiff" in raw for _, raw, _ in unique)
    defendant = sum("adjourn" in raw and "defendant" in raw for _, raw, _ in unique)
    generic = sum(status == "adjourned" and "plaintiff" not in raw and "defendant" not in raw
                  for status, raw, _ in unique)
    bankruptcy = sum(status == "bankruptcy" or "bankrupt" in raw for status, raw, _ in unique)
    return {
        "plaintiff_adjournments": plaintiff,
        "defendant_adjournments": defendant,
        "generic_adjournments": generic,
        "bankruptcy_events": bankruptcy,
        "distinct_status_events": len(unique),
    }


def score_sale_probability(
    state: str,
    sale_date: datetime | None,
    events: list[StatusEvent],
    now: datetime | None = None,
) -> tuple[float, dict[str, object]]:
    now = now or datetime.now(timezone.utc)
    counts = _event_counts(events)
    plaintiff = counts["plaintiff_adjournments"]
    defendant = counts["defendant_adjournments"]
    generic = counts["generic_adjournments"]
    bankruptcy = counts["bankruptcy_events"]

    probability = 0.40
    adjustments: list[dict[str, object]] = []

    adjournment_points = min(plaintiff + defendant + generic, 4) * 0.07
    if adjournment_points:
        probability += adjournment_points
        adjustments.append({"factor": "prior_distinct_adjournments", "change": adjournment_points})

    if state == "NJ" and defendant >= 2:
        probability += 0.10
        adjustments.append({"factor": "defendant_adjournment_allowance_reached", "change": 0.10})
    if state == "NJ" and plaintiff >= 2:
        probability += 0.10
        adjustments.append({"factor": "plaintiff_adjournment_allowance_reached", "change": 0.10})
    if state == "NJ" and plaintiff + defendant >= 4:
        probability += 0.06
        adjustments.append({"factor": "combined_adjournment_allowances_reached", "change": 0.06})

    if bankruptcy:
        probability += 0.04
        adjustments.append({"factor": "rescheduled_after_bankruptcy", "change": 0.04})

    days_until_sale = None
    if sale_date:
        comparable_date = sale_date if sale_date.tzinfo else sale_date.replace(tzinfo=timezone.utc)
        days_until_sale = (comparable_date.date() - now.date()).days
        proximity_change = 0.0
        if 0 <= days_until_sale <= 7:
            proximity_change = 0.10
        elif days_until_sale <= 14 and days_until_sale >= 0:
            proximity_change = 0.07
        elif days_until_sale <= 30 and days_until_sale >= 0:
            proximity_change = 0.04
        elif days_until_sale < 0:
            proximity_change = -0.12
        if proximity_change:
            probability += proximity_change
            adjustments.append({"factor": "sale_date_proximity", "change": proximity_change})

    probability = round(max(0.10, min(probability, 0.94)), 4)
    history_strength = min(counts["distinct_status_events"], 5) / 5
    confidence = round(0.30 + history_strength * 0.45 + (0.10 if sale_date else 0), 2)
    features: dict[str, object] = {
        **counts,
        "days_until_sale": days_until_sale,
        "confidence": min(confidence, 0.85),
        "adjustments": adjustments,
        "methodology": "Explainable heuristic; not calibrated from completed auction outcomes.",
        "nj_adjournment_assumption": "Two plaintiff and two defendant adjournments" if state == "NJ" else None,
    }
    return probability, features


def main() -> None:
    from app.database.session import engine

    now = datetime.now(timezone.utc)
    with engine.begin() as connection:
        sales = connection.execute(text("""SELECT id,state,current_sale_date
          FROM sheriff_sales WHERE current_status='scheduled'""")).mappings().all()
        created = 0
        for sale in sales:
            history_rows = connection.execute(text("""SELECT status,COALESCE(raw_status,status) raw_status,sale_date
              FROM sheriff_sale_status_history WHERE sheriff_sale_id=:id ORDER BY observed_at"""),
              {"id": sale["id"]}).mappings()
            events = [StatusEvent(row["status"], row["raw_status"], row["sale_date"])
                      for row in history_rows]
            probability, features = score_sale_probability(
                sale["state"], sale["current_sale_date"], events, now=now
            )
            connection.execute(text("""INSERT INTO sale_predictions(
              id,sheriff_sale_id,prediction_target,probability,predicted_class,model_name,
              model_version,feature_values,feature_explanations,predicted_at)
              VALUES(:id,:sale_id,'reaches_auction',:probability,:predicted_class,
              'status_history_heuristic',:version,CAST(:features AS JSONB),
              CAST(:explanations AS JSONB),:now)
              ON CONFLICT (sheriff_sale_id, prediction_target, model_version)
              DO UPDATE SET
                probability = EXCLUDED.probability,
                predicted_class = EXCLUDED.predicted_class,
                model_name = EXCLUDED.model_name,
                feature_values = EXCLUDED.feature_values,
                feature_explanations = EXCLUDED.feature_explanations,
                predicted_at = EXCLUDED.predicted_at"""),
              {"id": str(uuid.uuid4()), "sale_id": sale["id"], "probability": probability,
               "predicted_class": probability >= 0.65, "version": MODEL_VERSION,
               "features": json.dumps(features),
               "explanations": json.dumps(features["adjustments"]), "now": now})
            created += 1
    print(f"Created {created} auction-probability predictions ({MODEL_VERSION})")


if __name__ == "__main__":
    main()
