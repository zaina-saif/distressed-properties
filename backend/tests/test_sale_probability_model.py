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
