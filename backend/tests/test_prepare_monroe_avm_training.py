from datetime import date

from pipeline.prepare_monroe_avm_training import training_window_start


def test_training_window_uses_five_calendar_years() -> None:
    assert training_window_start(date(2022, 7, 26)) == date(2017, 1, 1)
