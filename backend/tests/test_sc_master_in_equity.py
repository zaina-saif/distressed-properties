from datetime import date

from pipeline.load_sc_master_in_equity import to_sale
from pipeline.scrape_sc_master_in_equity import parse_charleston, parse_greenville


def test_charleston_row():
    html = ("<table><tr><td>10-06-26 26-02681</td><td>Deutsche Bank</td><td>Kenneth R. Ellis</td>"
            "<td>3521600013 1371 Nye Street</td><td>$68,816.03</td><td>1 st</td>"
            "<td>John S. Kay 803-726-2700</td><td>West Ashley</td></tr></table>")
    record = parse_charleston(html)[0]
    assert (record["case"], record["sale_date"], record["street"], record["city"], record["parcel"]) == (
        "26-02681", "2026-10-06", "1371 Nye Street", "Charleston", "3521600013")


def test_greenville_row_and_withdrawn_flag():
    html = ("<table><tr><td>&#9747;</td><td></td><td>&#10003;</td><td></td><td>1</td><td>2019-CP-23-02758</td>"
            "<td>9 Chestatee Court<br>Simpsonville, SC 29680</td><td>Luke A. Burke</td><td>Burke Law, LLC</td>"
            "<td>River Shoals HOA</td><td>Ashley Johnson</td><td></td></tr></table>")
    record = parse_greenville(html, date(2026, 11, 2))[0]
    assert (record["street"], record["city"], record["zip_code"], record["withdrawn"]) == (
        "9 Chestatee Court", "Simpsonville", "29680", True)
    assert to_sale(record, date(2026, 10, 6)).status == "cancelled"


def test_past_listing_is_unverified():
    record = {"case": "1", "sale_date": "2026-10-05", "street": "1 A St", "city": "X", "zip_code": None,
              "parcel": None, "judgment": None, "plaintiff": None, "defendant": None, "attorney": None,
              "withdrawn": False}
    assert to_sale(record, date(2026, 10, 6)).status == "sold_or_cancelled_unverified"
