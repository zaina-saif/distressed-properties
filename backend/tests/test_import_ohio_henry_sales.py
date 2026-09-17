from pipeline.import_ohio_henry_sales import labeled_records, normalize_status, sale_date


def test_parses_labeled_record():
    text = """TUESDAY, MAY 5, 2025 AND TUESDAY, MAY 20, 2025
PLAINTIFF: BANK LLC
DEFENDANT: BORROWER, ET AL
CASE #: 24CV0049
ADDRESS: 415 HUBBARD ST, HAMLER
PARCEL #: 17-009212.0240
APPRAISED: $150,000.00
START BID: $100,000.00
PLAINTIFF ATTORNEY: COUNSEL NAME
SALE STATUS: SOLD 3RD PARTY $125,000
"""
    row = labeled_records(text)[0]
    assert row["CASE #"] == "24CV0049"
    assert row["ADDRESS"] == "415 HUBBARD ST, HAMLER"
    assert sale_date(text) == "2025-05-05"
    assert normalize_status(row["SALE STATUS"]) == "sold"


def test_status_normalization():
    assert normalize_status("WITHDRAWN") == "cancelled"
    assert normalize_status("RESCHEDULED FOR 2/6/24") == "postponed"
    assert normalize_status("UPCOMING") == "scheduled"
