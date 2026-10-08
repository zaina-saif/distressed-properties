from datetime import date

from pipeline.adapters.civilview_listing import parse_detail
from pipeline.load_civilview_states import normalize_status, to_sale

DETAIL = """<html><body><a>Back</a><div>Sheriff #:</div><div>24002443</div><div>Court Case #:</div><div>080702738</div>
<div>Sales Date:</div><div>10/6/2026</div><div>Property Address:</div><div>5033 SCHUYLER STREET</div>
<div>PHILADELPHIA PA 19144-4807</div><div>Debt Amount :</div><div>$167,156.68</div><div>Minimum Bid:</div>
<div>$29,900.00</div><div>OPA #:</div><div>133158300</div><h3>Status History</h3><table><tr><th>Status</th>
<th>Date</th></tr><tr><td>Postponed</td><td>10/6/2026</td></tr><tr><td>Scheduled - Mortgage Foreclosure</td>
<td>3/1/2022</td></tr></table></body></html>"""


def test_detail_page_fields_and_history():
    fields, history = parse_detail(DETAIL)
    assert fields["Property Address"] == ["5033 SCHUYLER STREET", "PHILADELPHIA PA 19144-4807"]
    assert history[0] == {"status": "Postponed", "date": "10/6/2026"}


def test_sale_from_detail():
    fields, history = parse_detail(DETAIL)
    sale = to_sale({"fields": fields, "status_history": history, "county_id": 60,
                    "detail_url": "https://x/Sales/SaleDetails?PropertyId=1"}, "PA")
    assert (sale.case, sale.street, sale.city, sale.zip_code) == ("24002443", "5033 SCHUYLER STREET", "Philadelphia", "19144")
    assert (sale.sale_date, sale.status, sale.upset, sale.judgment, sale.parcel) == (
        date(2026, 10, 6), "adjourned", 29900.0, 167156.68, "133158300")


def test_status_words():
    assert normalize_status("Continued") == "adjourned"
    assert normalize_status("Scheduled - Mortgage Foreclosure") == "scheduled"
    assert normalize_status("Withdrawn") == "cancelled"


from pipeline.load_civilview_states import address, amount_after


def test_one_line_addresses():
    assert address({"Address/Description": ["8739 EDINBURGH ST  NEW ORLEANS LA 70118"]}, "LA") == (
        "8739 EDINBURGH ST", "New Orleans", "70118")
    assert address({"Address": ["814 2ND STREET, NEVADA IA 50201"]}, "IA") == ("814 2ND STREET", "Nevada", "50201")


def test_located_at_phrase_and_trailing_city():
    fields = {"Address": ["SALE FOR REAL PROPERTY LOCATED AT 2036 112TH ST SW EVERETT WILL BE HELD AT: COURTHOUSE",
                          "EVERETT WA 98201"]}
    assert address(fields, "WA") == ("2036 112TH ST SW", "Everett", "98201")


def test_commonly_known_as_in_another_field():
    fields = {"Address": [], "Defendant": ["JOHN DOE; PARTIES IN POSSESSION OF THE REAL PROPERTY COMMONLY KNOWN AS : "
                                            "2116 WASHINGTON AVE CALDWELL, ID 83605"]}
    assert address(fields, "ID") == ("2116 WASHINGTON AVE", "Caldwell", "83605")
    assert address({"Address": [], "Defendant": ["NO ADDRESS HERE"]}, "ID") == ("", None, None)


def test_writ_amount_inside_a_value():
    assert amount_after({"Writ": ["Writ Assigned Date: 2/9/2026", "Writ Amount: $220,143.88"]}, "Writ Amount") == 220143.88
