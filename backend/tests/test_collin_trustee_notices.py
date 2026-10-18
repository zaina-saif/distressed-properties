from datetime import date

from pipeline.load_tx_trustee_sales import notice_details, sales_from
from pipeline.scrape_collin_trustee_notices import notices_from, parse_row

FIELDS = ["City: Fairview", "Sale Date: 11/03/2026", "File Date: 09/24/2026",
          "Property Type:Residential Single Family (A1)"]


def test_row_reads_address_dates_and_type():
    notice = parse_row("1004 REMINGTON CT \r\nFAIRVIEW, TX 75069", FIELDS)
    assert notice["street"] == "1004 Remington Ct" and notice["city"] == "Fairview" and notice["zip_code"] == "75069"
    assert notice["sale_date"] == "2026-11-03" and notice["file_date"] == "2026-09-24"
    assert notice["property_type"] == "Residential Single Family (A1)"
    assert notice["doc_id"] == "1004 REMINGTON CT|75069|2026-11-03" and notice["clerk_number"] is False


def test_batches_and_past_sales_are_left_out():
    rows = [("1004 REMINGTON CT \r\nFAIRVIEW, TX 75069", FIELDS),
            ("FILED 9/24/2026 - NOVEMBER SALE - MCKINNEY (2)", FIELDS),
            ("FILLED 9-24-2026-DECEMBER SALE-DALLAS", FIELDS),
            ("5 OLD ST \r\nPLANO, TX 75023", ["Sale Date: 10/06/2026"])]
    notices, unread, batches = notices_from(rows, date(2026, 10, 17))
    assert [notice["street"] for notice in notices] == ["1004 Remington Ct"]
    assert batches == 2 and unread == []


def test_collin_listing_details_name_no_document_number():
    notice = parse_row("1004 REMINGTON CT \r\nFAIRVIEW, TX 75069", FIELDS)
    sales, _ = sales_from({"notices": [notice]})
    assert sales[0].status == "scheduled_unverified"
    details = notice_details(notice, "Collin")
    assert details.startswith("Notice of Trustee's Sale, filed with the Collin County Clerk on September 24, 2026.")
    assert "Residential Single Family (A1)" in details and "foreclosure notices site" in details
