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
