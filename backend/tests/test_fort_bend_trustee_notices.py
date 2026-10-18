from datetime import date

from pipeline.scrape_fort_bend_trustee_notices import month_pdfs, notice_records, split_notices

FIRST = """24TX935-0326
3514 COVEY TRAIL DR, MISSOURI CITY, TX 77459
2026 AUG 20 AM10: 34
NOTICE OF FORECLOSURE SALE
The Property to be sold is described as follows:
LOT SIX (6), IN BLOCK TEN (10), OF QUAIL VALLEY SUBDIVISION, A SUBDIVISION IN FORT BEND COUNTY, TEXAS
November 03, 2026, at 1:00 PM, at The Fort Bend County Gus George Academy-Patton Hall, 1521 Eugene Heimann Circle,
Richmond, TX 77469, or as designated by the County Commissioners Court."""
SECOND_PAGE = "Substitute Trustee(s): ...\nCertificate of Posting"
COURTESY = "2026 OCT 01\nNOTICE\nAs a courtesy, this foreclosure list is images and available to the public."


def test_month_pdfs_keeps_upcoming_lists():
    html = ('<a href="https://www.fortbendcountytx.gov/sites/x/research-foreclosures/November-2026.pdf">Nov</a>'
            '<a href="/sites/x/research-foreclosures/October-2026.pdf">Oct</a>')
    assert month_pdfs(html, date(2026, 10, 17)) == [
        (date(2026, 11, 3), "https://www.fortbendcountytx.gov/sites/x/research-foreclosures/November-2026.pdf")]


def test_notices_split_at_file_stamps_and_skip_the_courtesy_page():
    notices = split_notices([COURTESY, FIRST, SECOND_PAGE, FIRST.replace("3514 COVEY", "77 OTHER")])
    assert [(page, filed) for page, _, filed in notices] == [(1, "2026-08-20"), (3, "2026-08-20")]
    assert "Certificate of Posting" in notices[0][1]


def test_records_take_the_property_not_the_sale_venue():
    [record] = notice_records([FIRST, SECOND_PAGE], date(2026, 11, 3))
    assert record["street"].upper() == "3514 COVEY TRAIL DR" and record["city"] == "Missouri City"
    assert record["doc_id"] == "3514 COVEY TRAIL DR|77459|2026-11-03" and record["file_date"] == "2026-08-20"
    assert record["clerk_number"] is False and record["list_page"] == 1
