from pipeline.scrape_tjsc_upcoming_sales import _money, _sale_datetime


def test_tjsc_opening_bid_parsing():
    assert _money("$125,500.00") == 125500.0
    assert _money("TBD") is None


def test_tjsc_sale_datetime_parsing():
    assert _sale_datetime("9/23/2026", "10:30 AM") == "2026-09-23T10:30:00"
