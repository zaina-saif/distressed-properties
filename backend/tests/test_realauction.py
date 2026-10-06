from datetime import date

from pipeline.adapters.realauction import calendar_days, parse_items
from pipeline.load_realauction_sales import address, case_number, current_items, status


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
