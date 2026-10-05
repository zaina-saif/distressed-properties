from pipeline.train_sale_probability_model import _terminal_label, build_training_rows


def test_unverified_outcome_is_not_a_sale():
    assert _terminal_label({"status": "sold_or_cancelled_unverified"}) is None


def test_terminal_labels():
    assert _terminal_label({"status": "sold"}) == 1
    assert _terminal_label({"status": "purchased_-_3rd_party"}) == 1
    assert _terminal_label({"status": "cancelled"}) == 0
    assert _terminal_label({"status": "redeemed"}) == 0


def test_current_terminal_status_labels_last_scheduled_event():
    sale = {"id": "s1", "state": "NJ", "county": "Middlesex", "current_status": "purchased_-_3rd_party",
            "current_sale_date": "2025-05-01", "upset_price": 100000, "judgment_amount": None}
    history = {"s1": [{"id": "e1", "status": "scheduled", "raw_status": "Scheduled", "sale_date": "2025-05-01"}]}

    rows = build_training_rows([sale], history)

    assert [row["label"] for row in rows] == [1]


def test_unverified_current_status_produces_no_label():
    sale = {"id": "s1", "state": "NJ", "county": "Union", "current_status": "sold_or_cancelled_unverified",
            "current_sale_date": "2025-05-01", "upset_price": None, "judgment_amount": None}
    history = {"s1": [{"id": "e1", "status": "scheduled", "raw_status": "Scheduled", "sale_date": "2025-05-01"}]}

    assert build_training_rows([sale], history) == []


def test_unmatured_scheduled_events_are_left_out():
    from datetime import date

    sale = {"id": "s1", "state": "NJ", "county": "Essex", "current_status": "cancelled",
            "current_sale_date": "2026-12-01", "upset_price": None, "judgment_amount": None}
    history = {"s1": [
        {"id": "e1", "status": "scheduled", "raw_status": "Scheduled", "sale_date": "2026-06-01"},
        {"id": "e2", "status": "scheduled", "raw_status": "Scheduled", "sale_date": "2026-12-01"},
        {"id": "e3", "status": "cancelled", "raw_status": "Cancelled", "sale_date": "2026-11-01"},
    ]}

    rows = build_training_rows([sale], history, as_of=date(2026, 10, 5))

    assert [row["event_date"] for row in rows] == ["2026-06-01"]


def test_explain_drivers_reports_points_against_typical():
    import pandas as pd

    from pipeline.train_sale_probability_model import explain_drivers

    class Model:
        # Probability falls 10 points per adjournment.
        def predict_proba(self, frame):
            p = 0.6 - 0.1 * frame["adjournment_count"].astype(float)
            return pd.concat([1 - p, p], axis=1).to_numpy()

    columns = ["adjournment_count", "plaintiff_adjournment_count", "defendant_adjournment_count",
               "court_adjournment_count", "county"]
    frame = pd.DataFrame([{"adjournment_count": 3, "plaintiff_adjournment_count": 2,
                           "defendant_adjournment_count": 1, "court_adjournment_count": 0, "county": "Essex"}])
    typical = {"adjournment_count": 1, "plaintiff_adjournment_count": 1, "defendant_adjournment_count": 0,
               "court_adjournment_count": 0, "county": "Essex"}

    drivers = explain_drivers(Model(), frame, columns, typical)[0]

    assert drivers[0]["key"] == "adjournments"
    assert drivers[0]["impact"] == -0.2
    assert drivers[0]["value"] == "3 (2 plaintiff, 1 defendant)"
