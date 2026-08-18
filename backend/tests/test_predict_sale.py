from datetime import datetime, timezone

from pipeline.predict_sale import StatusEvent, score_sale_probability


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
