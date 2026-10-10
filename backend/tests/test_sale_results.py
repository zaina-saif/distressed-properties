from datetime import date
from decimal import Decimal

from pipeline.sale_results import classify_buyer, parse_sale_result

CIVILVIEW_PAGE = (
    "Status History\nStatus\nDate\nAmount\n[Collapse All]\n"
    "Scheduled\n3/5/2025\n$0.00\n"
    "Plaintiff Adjourned to\n10/1/2025\n$0.00\n"
    "Purchased - 3rd Party\n10/1/2025\n$427,000.00\n"
    "*Excludes Judgment Interest and Sheriff Fees."
)


def test_reads_the_winning_bid_from_the_status_history_table():
    result = parse_sale_result(CIVILVIEW_PAGE)
    assert result is not None
    assert result.buyer == "third_party"
    assert result.amount == Decimal("427000.00")
    assert result.sold_on == date(2025, 10, 1)
    assert result.raw_status == "Purchased - 3rd Party"


def test_a_zero_amount_means_none_was_published():
    result = parse_sale_result("Purchased - Plaintiff\n4/2/2026\n$0.00\n")
    assert result is not None and result.buyer == "plaintiff" and result.amount is None


def test_falls_back_to_an_amount_written_in_the_status_text():
    result = parse_sale_result(None, ["Scheduled", "SOLD: 3RD PARTY FOR $ 68,100.00"], date(2026, 9, 14))
    assert result is not None
    assert result.buyer == "third_party"
    assert result.amount == Decimal("68100.00")
    assert result.sold_on == date(2026, 9, 14)


def test_buyer_without_an_amount():
    result = parse_sale_result("No history here", ["Scheduled", "Purchased - Buy Back"], None)
    assert result is not None and result.buyer == "plaintiff" and result.amount is None


def test_not_sold_returns_none():
    assert parse_sale_result("Scheduled\n3/5/2025\n$0.00\n", ["Scheduled", "Cancelled"]) is None


def test_buyer_classification():
    assert classify_buyer("Purchased - Third Party") == "third_party"
    assert classify_buyer("Purchased at Auction by 3rd Party") == "third_party"
    assert classify_buyer("Purchased at Auction by Plaintiff (Buy Back)") == "plaintiff"
    assert classify_buyer("Purchased - Plaintiff FHA/HUD CAFMV") == "plaintiff"
    assert classify_buyer("SOLD TO PL,AINTIFF FOR $80,000") == "not_stated"
    assert classify_buyer("Purchased - 3rd Party - CWPP") == "cwpp"
    assert classify_buyer("Purchased - Foreclosure") == "not_stated"
