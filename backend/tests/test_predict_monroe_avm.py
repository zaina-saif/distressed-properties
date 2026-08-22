from datetime import date

from pipeline.predict_monroe_avm import feature_frame


def test_monroe_prediction_features_use_effective_date() -> None:
    frame = feature_frame([{"acreage": 1.0}], date(2026, 8, 22))
    assert frame.iloc[0]["sale_year"] == 2026
    assert frame.iloc[0]["sale_month"] == 8
