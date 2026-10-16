from datetime import date

from pipeline.ny_case_summary import build_summary


def case(**extra):
    return {"county": "New York", "index_number": "850143/2025", "property_address": "67 West 131st Street",
            "city": "New York", "zip": "10037", "borough_block_lot": "1-1729-7/9", "plaintiff": "BANK, ",
            "plaintiff_attorney": "LAW LLP", "referee_name": "Thomas Kleinberger", "justice": None,
            "filing_date": "2025-04-02", "initiating_doc": "Summons and Complaint", "original_mortgagee": None,
            "unpaid_principal": None, "approximate_judgment": 7088728.13, "approximate_lien_amount": None,
            "judgment_date": "2026-07-22", "defendant": "OWNER, A", **extra}


def test_the_case_reads_as_stages_in_order():
    summary = build_summary(case(
        appearances=[
            {"appearance_date": "2025-11-26", "part": "MOTION", "justice": "J", "purpose": "Motion-Other", "outcome": "Adjourned"},
            {"appearance_date": "2026-04-15", "part": "CONF", "justice": "J", "purpose": "Conference-Status", "outcome": "Held"},
            {"appearance_date": "2026-07-17", "part": "MOTION", "justice": "J", "purpose": "Motion-Other", "outcome": "Fully Submitted"},
        ],
        events=[
            {"auction_date": "2026-10-20", "time": "14:15", "outcome": "Not Held", "event_status": "not_held",
             "remarks": "60 CENTRE STREET ROOM 130 CANCELED DUE TO FAILURE TO FILE NOTICE OF SALE"},
            {"auction_date": "2026-12-01", "time": "14:15", "outcome": None, "event_status": "scheduled",
             "remarks": "60 CENTRE STREET ROOM 130"},
        ]), ["summons_complaint", "notice_of_sale", "appearances"], date(2026, 10, 16))
    assert [stage["stage"] for stage in summary["stages"]] == [
        "Case filed", "Motions", "Settlement and status conferences", "Judgment of foreclosure and sale",
        "Auction taken off the calendar", "Next auction"]
    assert summary["stages"][1]["detail"] == "2 court dates, 2025-11-26 to 2026-07-17; last outcome: Fully Submitted"
    assert summary["next_auction"] == {"date": "2026-12-01", "time": "2:15 PM", "location": "60 Centre Street Room 130",
                                       "outcome": None, "status": "scheduled", "remarks": None}
    assert summary["auction_calendar"][0]["remarks"] == "CANCELED DUE TO FAILURE TO FILE NOTICE OF SALE"
    assert summary["plaintiff"] == "BANK" and "OWNER" not in str(summary)
    assert summary["sources"][-1] == "WebCivil auction calendar"


def test_past_auctions_count_from_the_appearances():
    summary = build_summary(case(appearances=[
        {"appearance_date": "2024-04-12", "part": "AUCTION", "justice": None, "purpose": "Auction-Foreclosed Property", "outcome": "Sold"},
        {"appearance_date": "2025-06-06", "part": "AUCTION", "justice": None, "purpose": "Auction-Foreclosed Property", "outcome": "Not Held"},
    ], events=[]), [], date(2026, 10, 16))
    auctions = next(stage for stage in summary["stages"] if stage["stage"] == "Auctions scheduled")
    assert auctions["detail"].startswith("2 auction dates so far, 2024-04-12 to 2025-06-06; 1 not held; recorded as sold on 2024-04-12")
    assert summary["next_auction"] is None


def test_a_scheduled_date_that_went_by_is_no_longer_the_next_auction():
    summary = build_summary(case(appearances=[], events=[
        {"auction_date": "2026-10-20", "time": "14:15", "outcome": None, "event_status": "scheduled", "remarks": None},
        {"auction_date": "2026-12-01", "time": "14:15", "outcome": None, "event_status": "scheduled", "remarks": None},
    ]), [], date(2026, 10, 21))
    assert summary["auction_calendar"][0]["status"] == "passed"
    assert summary["next_auction"]["date"] == "2026-12-01"
    assert next(s for s in summary["stages"] if s["stage"] == "Auctions scheduled")["detail"].startswith("1 auction date so far")
