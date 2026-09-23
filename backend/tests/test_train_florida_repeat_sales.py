import pandas as pd

from pipeline.train_florida_repeat_sales import county_month_indices, evaluate_window, prepare_sales


def test_repeat_sale_index_uses_only_history_before_cutoff() -> None:
    source = pd.DataFrame([
        {"id": 1, "county": "Lake", "source_parcel_id": "A", "sale_date": "2025-01-01", "sale_price": 100_000},
        {"id": 2, "county": "Lake", "source_parcel_id": "B", "sale_date": "2025-02-01", "sale_price": 110_000},
        {"id": 3, "county": "Lake", "source_parcel_id": "A", "sale_date": "2025-03-01", "sale_price": 120_000},
        {"id": 4, "county": "Lake", "source_parcel_id": "C", "sale_date": "2025-01-01", "sale_price": 100_000},
        {"id": 5, "county": "Lake", "source_parcel_id": "C", "sale_date": "2025-03-01", "sale_price": 120_000},
    ])
    frame = prepare_sales(source)
    indices, _ = county_month_indices(frame, pd.Timestamp("2025-03-01"), 1)
    assert indices[("Lake", pd.Period("2025-02"))] == 110_000
    assert ("Lake", pd.Period("2025-03")) not in indices
    result = evaluate_window(frame, pd.Timestamp("2025-03-01"), pd.Timestamp("2025-04-01"),
                             pd.Timestamp("2025-03-01"), 1)
    assert result["rows"] == 2
    assert result["unchanged_prior_sale"]["mae"] == 20_000
