from datetime import datetime, timezone

from pipeline.predict_sale import StatusEvent, score_sale_probability
from pipeline.train_sale_probability_model import build_features, build_training_rows


NOW = datetime(2026, 8, 13, tzinfo=timezone.utc)


def test_exhausted_nj_adjournments_raise_probability():
    events = [
        StatusEvent("adjourned", "Adjournment Defendant", datetime(2026, 5, 1, tzinfo=timezone.utc)),
        StatusEvent("adjourned", "Adjournment Defendant", datetime(2026, 6, 1, tzinfo=timezone.utc)),
        StatusEvent("adjourned", "Adjournment Plaintiff", datetime(2026, 7, 1, tzinfo=timezone.utc)),
        StatusEvent("adjourned", "Adjournment Plaintiff", datetime(2026, 8, 1, tzinfo=timezone.utc)),
    ]
    probability, features = score_sale_probability(
        "NJ", datetime(2026, 8, 20, tzinfo=timezone.utc), events, NOW
    )
    assert probability == 0.94
    assert features["plaintiff_adjournments"] == 2
    assert features["defendant_adjournments"] == 2


def test_duplicate_observations_are_not_multiple_adjournments():
    event = StatusEvent("adjourned", "Adjournment Defendant", datetime(2026, 7, 1, tzinfo=timezone.utc))
    probability, features = score_sale_probability(
        "NJ", datetime(2026, 10, 1, tzinfo=timezone.utc), [event, event, event], NOW
    )
    assert probability == 0.47
    assert features["defendant_adjournments"] == 1


def test_missing_history_uses_baseline_plus_date_proximity():
    probability, features = score_sale_probability(
        "PA", datetime(2026, 8, 20, tzinfo=timezone.utc), [], NOW
    )
    assert probability == 0.50
    assert features["confidence"] == 0.4


def test_training_rows_use_only_history_before_each_scheduled_event():
    sale = {
        "id": "sale-1", "state": "NJ", "county": "Bergen",
        "current_status": "sold", "current_sale_date": datetime(2026, 8, 1, tzinfo=timezone.utc),
        "upset_price": 100000, "judgment_amount": 120000,
    }
    histories = {
        "sale-1": [
            {"id": "1", "status": "scheduled", "raw_status": "Scheduled", "sale_date": datetime(2026, 5, 1, tzinfo=timezone.utc)},
            {"id": "2", "status": "adjourned", "raw_status": "Adjourned - Defendant", "sale_date": datetime(2026, 6, 1, tzinfo=timezone.utc)},
            {"id": "3", "status": "scheduled", "raw_status": "Scheduled", "sale_date": datetime(2026, 7, 1, tzinfo=timezone.utc)},
            {"id": "4", "status": "sold", "raw_status": "Purchased - 3rd Party", "sale_date": datetime(2026, 8, 1, tzinfo=timezone.utc)},
        ]
    }
    rows = build_training_rows([sale], histories)
    assert len(rows) == 2
    assert rows[0]["label"] == 1
    assert rows[0]["adjournment_count"] == 0
    assert rows[1]["label"] == 1
    assert rows[1]["adjournment_count"] == 1
