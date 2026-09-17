from pipeline.import_ohio_scioto_sales import normalize_status, result_amount


def test_statuses():
    assert normalize_status("CANCELLED") == "cancelled"
    assert normalize_status("POSTPONED TO 7/15/26") == "postponed"
    assert normalize_status("SOLD: 3RD PARTY FOR $ 48,900.00") == "sold"
    assert normalize_status("NO BIDS: 2ND SALE ON 4/1/26") == "unsold"


def test_result_amount():
    assert result_amount("BACK TO PLAINTIFF FOR $ 20,000.00") == "20000.00"
    assert result_amount("CANCELLED") is None
