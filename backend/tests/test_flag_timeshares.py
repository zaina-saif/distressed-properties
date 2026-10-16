import re

from pipeline.flag_timeshares import NOT_TIMESHARE, TIMESHARE


def matches(value: str) -> bool:
    return bool(re.search(TIMESHARE, value, re.I)) and not re.search(NOT_TIMESHARE, value, re.I)


def test_timeshare_wordings():
    assert matches("519 Fairway Lane, Timeshare Estate No. 32")
    assert matches("630 Fairway Lane Time Share Estate No. 49")
    assert matches("OCCUPANCY STATUS: PROPERTY IS NOT VACANT ... BUT INSTEAD IS A TIMESHARE VACATION PROPERTY")
    assert not matches("The property is not a timeshare.")
    assert not matches("12 Main Street, Unit 4")
