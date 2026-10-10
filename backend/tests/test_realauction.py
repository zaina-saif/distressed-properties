from datetime import date

from pipeline.adapters.realauction import calendar_days, parse_items, parse_result
from pipeline.load_realauction_sales import (address, case_number, current_items, history_items, result_status,
                                            result_text, status)
from pipeline.sale_results import parse_sale_result


def test_ohio_address():
    fields = {"Property Address": "11713 GAY AVENUE", "Property Address 2": "CLEVELAND , 441050000"}
    assert address(fields, "OH") == ("11713 GAY AVENUE", "CLEVELAND", "44105")


def test_florida_address():
    fields = {"Property Address": "8155 NW 201 ST", "Property Address 2": "HIALEAH, FL- 33015"}
    assert address(fields, "FL") == ("8155 NW 201 ST", "HIALEAH", "33015")


def test_ohio_case_number_carries_sheriff_number():
    assert case_number({"Case #": " CV11762673 (66355)"}) == ("CV11762673", "66355")
    assert case_number({"Case #": " 2014-020661-CA-01"}) == ("2014-020661-CA-01", None)


def test_closed_listing_status_depends_on_sale_day():
    today = date(2026, 10, 5)
    assert status({"area": "W", "sale_date": "2026-10-05"}, today) == "scheduled"
    assert status({"area": "C", "sale_date": "2026-10-07"}, today) == "cancelled"
    assert status({"area": "C", "sale_date": "2026-10-05"}, today) == "sold_or_cancelled_unverified"


def test_latest_listing_wins():
    items = [{"area": "C", "sale_date": "2026-10-07", "fields": {"Case #": "A1"}},
             {"area": "W", "sale_date": "2026-11-04", "fields": {"Case #": "A1"}}]
    assert current_items(items, date(2026, 10, 5))["A1"]["sale_date"] == "2026-11-04"


def test_calendar_and_items_parse():
    calendar = ("<div class='CALBOX CALW5' dayid='10/07/2026' ><span class='CALNUM'>7</span> <span class='CALTEXT'>"
                "<b>Foreclosure</b><br><span class='CALMSG'><span class=\"CALACT\">0</span> / "
                "<span  class=\"CALSCH\">99</span> FC</span></span></div>")
    assert calendar_days(calendar) == [(date(2026, 10, 7), "Foreclosure", 99)]
    item = ('<div id="AITEM_57005" aid="57005">@A@E_DETAILS"><@I><tbody><tr><th @CAD_LBL" scope="row">Parcel ID:</th>'
            '<td @CAD_DTA"> 13714063@G</tbody></@I>@B')
    assert parse_items(item)[0]["fields"] == {"Parcel ID": "13714063"}


def test_texas_address_drops_zip_plus_four():
    fields = {"Property Address": "3322 UTAH AVE", "Property Address 2": "DALLAS, TX 75216-5234"}
    assert address(fields, "TX") == ("3322 UTAH AVE", "DALLAS", "75216")


def test_texas_cause_number_carries_precinct():
    assert case_number({"Cause Number": "TX-24-01693 (8)"}) == ("TX-24-01693", "8")


def test_texas_tracts_in_one_suit_stay_separate():
    items = [{"area": "W", "sale_date": "2026-11-03",
              "fields": {"Cause Number": "TX-24-01693 (8)", "Account Number": account}} for account in ("111", "222")]
    assert sorted(current_items(items, date(2026, 10, 9))) == ["TX-24-01693:111", "TX-24-01693:222"]


def test_sold_result_carries_amount_and_buyer():
    result = parse_result({"A": "Auction Sold", "B": "09/28/2026 09:03 AM ET", "C": "Amount", "D": "$69,000.00",
                           "SL": "Sold To", "ST": "3rd Party Bidder"})
    item = {"area": "C", "sale_date": "2026-09-28", "result": result}
    assert status(item, date(2026, 10, 9)) == "sold"
    text = result_text(item)
    assert text == "Auction Sold to 3rd Party Bidder for $69,000.00"
    sold = parse_sale_result(None, [text])
    assert sold.buyer == "third_party" and str(sold.amount) == "69000.00"


def test_plaintiff_and_unsold_results():
    plaintiff = parse_result({"A": "Auction Sold", "B": "x", "D": "$33,334.00", "SL": "Sold To", "ST": "Plaintiff "})
    assert result_status(plaintiff) == "sold"
    assert parse_sale_result(None, [result_text({"result": plaintiff})]).buyer == "plaintiff"
    unsold = parse_result({"A": "Auction Sold", "B": "x", "D": "$76,667.00", "SL": "Unsold", "ST": ""})
    assert result_status(unsold) == "unsold"
    assert parse_sale_result(None, [result_text({"result": unsold})]) is None


def test_status_results():
    for text, expected in [("Canceled per County", "cancelled"), ("CANCELLED BANKRUPTCY CH 13", "bankruptcy"),
                           ("POSTPONED BY ATTORNEY", "adjourned"), ("Redeemed", "redeemed"),
                           ("WITHDRAWN – TAX DELINQUENT", "cancelled"), ("Bidder Walked Away", None)]:
        assert result_status(parse_result({"A": "B", "B": text})) == expected, text


def test_closed_without_result_stays_unverified():
    assert status({"area": "C", "sale_date": "2026-09-28"}, date(2026, 10, 9)) == "sold_or_cancelled_unverified"


def test_history_items_are_in_date_order():
    items = [{"sale_date": "2026-09-28", "area": "C", "fields": {"Case #": "CV1 (1)"}},
             {"sale_date": "2026-08-03", "area": "C", "fields": {"Case #": "CV1 (1)"}}]
    assert [item["sale_date"] for _, item in history_items(items)] == ["2026-08-03", "2026-09-28"]
