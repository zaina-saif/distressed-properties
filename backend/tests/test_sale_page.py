from app.api.sale_page import _find_detail_link, parse_detail_page
from bs4 import BeautifulSoup

DETAIL = """
<h1>Sales Listing Detail (Camden County, NJ)</h1>
<div class="sale-detail-item"><div class="sale-detail-label">Sheriff #:</div><div class="sale-detail-value"> FR-25002305 </div></div>
<div class="sale-detail-item"><div class="sale-detail-label">Address:</div><div class="sale-detail-value">14 CHAPEL CIRCLE<br/>SICKLERVILLE NJ 08081</div></div>
<table id="longTable"><tr><th>Status</th><th>Date</th></tr><tr><td>Scheduled</td><td>9/2/2026</td></tr></table>
<p>*Excludes Judgment Interest and Sheriff Fees.</p>
"""


def test_parse_detail_page_keeps_labels_values_and_history():
    page = parse_detail_page(DETAIL)

    assert page["title"] == "Sales Listing Detail (Camden County, NJ)"
    assert page["fields"] == [
        {"label": "Sheriff #", "value": "FR-25002305"},
        {"label": "Address", "value": "14 CHAPEL CIRCLE\nSICKLERVILLE NJ 08081"},
    ]
    assert page["status_history"] == [{"status": "Scheduled", "date": "9/2/2026"}]
    assert page["notes"] == ["*Excludes Judgment Interest and Sheriff Fees."]


def test_find_detail_link_matches_exact_sheriff_number():
    soup = BeautifulSoup(
        '<tr><td><a href="/Sales/SaleDetails?PropertyId=1">View</a></td><td>F-1001</td></tr>'
        '<tr><td><a href="/Sales/SaleDetails?PropertyId=2">View</a></td><td>F-100</td></tr>',
        "html.parser",
    )

    assert _find_detail_link(soup, "f-100").endswith("PropertyId=2")
    assert _find_detail_link(soup, "F-999") is None


def test_parse_sale_logistics_from_common_notice_wordings():
    from app.api.sale_page import parse_sale_logistics

    passaic = parse_sale_logistics(
        "public vendue on Tuesday THE 6th DAY OF October 2026 between the hours of two and five o'clock in the "
        "afternoon of said day, that is to say at 2:00 P.M. prevailing time at Commissioner’s Meeting Room, Room 220 "
        "Administration Building, 401 Grand Street, Paterson, New Jersey to wit: All that tract"
    )
    assert passaic == {"time": "2:00 PM", "location": "Commissioner’s Meeting Room, Room 220 Administration Building, 401 Grand Street, Paterson, New Jersey"}

    monmouth = parse_sale_logistics(
        "public vendue, at Monmouth County Sheriff’s Office Public Safety Center, 2500 Kozloski Road, in the township of "
        "Freehold, county of Monmouth, New Jersey, on Tuesday, the 13th day of October, 2026 at 1 o’clock, P.M. prevailing time."
    )
    assert monmouth["time"] == "1:00 PM"
    assert monmouth["location"].startswith("Monmouth County Sheriff’s Office Public Safety Center")

    gloucester = parse_sale_logistics(
        "will be exposed for sale at Public Venue, on Wednesday, October 14, 2026, to-wit, at 2 o’clock in the afternoon "
        "prevailing time, at 1 N. Broad Street, Ceremonial Courtroom 201 in the City of Woodbury, County of Gloucester and State of New Jersey, all"
    )
    assert gloucester["time"] == "2:00 PM"
    assert gloucester["location"].startswith("1 N. Broad Street")

    middlesex = parse_sale_logistics("that is to say at 1:30 P.M. prevailing time at The Heldrich Hotel, 10 Livingston Avenue, New Brunswick, New Jersey 08901 to wit")
    assert middlesex == {"time": "1:30 PM", "location": "Heldrich Hotel, 10 Livingston Avenue, New Brunswick, New Jersey 08901"}


def test_parse_sale_logistics_returns_none_when_not_stated():
    from app.api.sale_page import parse_sale_logistics

    assert parse_sale_logistics("Sheriff #: FR-1 Sales Date: 10/7/2026") == {"time": None, "location": None}


def test_parse_sale_logistics_location_ending_in_nj_abbreviation():
    from app.api.sale_page import parse_sale_logistics

    essex = parse_sale_logistics("at 1:30 PM prevailing time at Leroy F. Smith Building, 60 West Market Street, 14th Floor, Newark, NJ 07102 to wit: All that tract, State of New Jersey")
    assert essex["location"] == "Leroy F. Smith Building, 60 West Market Street, 14th Floor, Newark, NJ 07102"
