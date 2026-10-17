from datetime import date

from pipeline.load_tx_trustee_sales import notice_details, sales_from
from pipeline.scrape_bexar_trustee_notices import notices_from


def feature(doc, year, month, address, kind="MORTGAGE"):
    return {"attributes": {"DOC_NUMBER": doc, "YEAR": year, "MONTH": month, "ADDRESS": address, "CITY": "SAN ANTONIO",
                           "ZIP": "78220", "TYPE": kind}, "geometry": {"x": -98.44, "y": 29.41}}


def test_upcoming_mortgage_notices_only_with_first_tuesday_sale_date():
    notices = notices_from([feature("20261100001", 2026, 11, "122  MORNINGVIEW DR"),
                            feature("20261000005", 2026, 10, "5 PAST ST"),
                            feature("20261100009", 2026, 11, "9 TAX ST", kind="TAX")], date(2026, 10, 17))
    assert [notice["doc_id"] for notice in notices] == ["20261100001"]
    notice = notices[0]
    assert notice["sale_date"] == "2026-11-03" and notice["street"] == "122 Morningview Dr"
    assert notice["city"] == "San Antonio" and notice["latitude"] == 29.41


def test_bexar_notices_load_as_trustee_sales_with_coordinates():
    notices = notices_from([feature("20261100001", 2026, 11, "122 MORNINGVIEW DR"),
                            feature("20261100345", 2026, 11, "LOOP 410 (1298144)")], date(2026, 10, 17))
    sales, without_address = sales_from({"notices": notices})
    assert [sale.case for sale in sales] == ["20261100001"] and len(without_address) == 1
    assert sales[0].status == "scheduled_unverified" and sales[0].longitude == -98.44
    assert "foreclosure map" in notice_details(notices[0], "Bexar")
