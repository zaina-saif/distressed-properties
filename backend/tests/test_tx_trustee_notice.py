from pipeline.parse_tx_trustee_notice import lender, parse_notice
from pipeline.scrape_harris_trustee_notices import first_tuesday, result_rows

from bs4 import BeautifulSoup

NARRATIVE = """TENESHIA HUDSPETH, COUNTY CLERK, HARRIS COUNTY, TEXAS
FRCL-2026-0001
FILED 8/6/2026 9:26:54 AM
1610 Example Drive, Crosby, TX 77532
NOTICE OF SUBSTITUTE TRUSTEE'S SALE
Place:
The Bayou City Event Center located at 9401 Knight Road, Houston, TX 77045
4. Obligations Secured. Deed of Trust or Contract Lien executed by JANE DOE, securing the payment of the indebtedness
in the original amount of $278,354.00, and obligations therein described. Example Mortgage, LLC is the current mortgagee
of the note and Deed of Trust or Contract Lien.
5. Property to be Sold. LOT ONE (1), IN BLOCK TWO (2), OF NEWPORT SEC 4 PARTIAL REPLAT NO. 2,
A SUBDIVISION IN HARRIS COUNTY, TEXAS ACCORDING TO THE MAP OR PLAT THEREOF RECORDED AT FILM CODE NO. 692763.
Kirk Example, Esq., whose address is 1770 St. James Place, Suite 150, Houston, Texas 77056
"""

FORM = """NOTICE OF ACCELERATION AND NOTICE OF TRUSTEE'S SALE
Grantor(s):
Original
Mortgagee:
Original Principal:
Property:
Property Address:
December 9, 1999
JOHN ROE
$40,740.00
Lot 10, Block 1, of SUNSET MEADOW, a subdivision in Harris County, Texas
12400 Example Circle
Houston, TX 77099
MORTGAGE SERVICING INFORMATION:
Current Mortgagee: Example Asset Company, Inc.
Mortgage Servicer
75 Beattie Place
Greenville, SC 29601
Substitute Trustee Address:
546 Silicon Dr., Suite 103, Southlake, TX 76092
"""


def test_a_narrative_notice_gives_its_address_loan_lender_and_legal_description():
    result = parse_notice(NARRATIVE)
    assert (result["street"], result["city"], result["zip_code"]) == ("1610 Example Drive", "Crosby", "77532")
    assert result["address_source"] == "inferred"  # the venue and the law firm are left out
    assert result["original_principal"] == 278354.0
    assert result["lender"] == "Example Mortgage, LLC"
    assert (result["lot"], result["block"]) == ("1", "2")
    assert result["legal_description"].startswith("LOT ONE (1), IN BLOCK TWO (2)")
    assert "JANE DOE" not in str(result)


def test_a_two_column_form_read_out_of_order_still_gives_the_property():
    result = parse_notice(FORM)
    assert (result["street"], result["city"], result["zip_code"]) == ("12400 Example Circle", "Houston", "77099")
    assert result["original_principal"] == 40740.0
    assert result["lender"] == "Example Asset Company, Inc"
    assert result["subdivision"] == "SUNSET MEADOW"
    assert "JOHN ROE" not in str(result)


def test_a_labeled_address_wins_and_ocr_zip_slips_are_fixed():
    text = "Lender: Example Realty, LLC\nCommonly known as: 2630 Example St, Houston, TX 7709S\n" \
           "Mailing address 4400 Post Oak Parkway, Houston, Texas 77027\n"
    result = parse_notice(text)
    assert (result["street"], result["zip_code"], result["address_source"]) == ("2630 Example St", "77095", "labeled")
    assert result["lender"] == "Example Realty, LLC"


def test_no_address_when_the_notice_has_only_a_legal_description():
    result = parse_notice("1. Property to Be Sold. The property to be sold is described as follows: LOT 24, BLOCK 10, "
                          "OF TIMBER COVE ADDITION, SECTION TWO (2), A SUBDIVISION IN HARRIS COUNTY, TEXAS, ACCORDING "
                          "TO THE MAP. Sale at 9401 Knight Road, Houston, TX 77045")
    assert result["street"] is None and result["address_candidates"] == 0
    assert (result["lot"], result["block"]) == ("24", "10")


def test_an_association_lien_is_told_apart_from_a_deed_of_trust():
    text = "NOTICE OF FORECLOSURE SALE\nExample Homeowners Association, Inc. assessments owed under the Declaration\n"
    assert parse_notice(text)["notice_kind"] == "association_assessment_lien"
    assert parse_notice("Deed of Trust dated 2020. " + text)["notice_kind"] == "deed_of_trust"


def test_sales_are_on_the_first_tuesday():
    assert first_tuesday(2026, 11).isoformat() == "2026-11-03"
    assert first_tuesday(2026, 12).isoformat() == "2026-12-01"


def test_the_clerk_results_grid_is_read():
    html = """<table><tr><td></td><td><a href="ViewECdocs.aspx?ID=abc">FRCL-2026-5654</a></td>
        <td>11/03/2026</td><td>08/06/2026</td><td>2</td></tr></table>"""
    assert result_rows(BeautifulSoup(html, "html.parser")) == [{
        "doc_id": "FRCL-2026-5654", "sale_date": "2026-11-03", "file_date": "2026-08-06", "pages": 2,
        "href": "ViewECdocs.aspx?ID=abc"}]


def test_ocr_slips_in_the_street_city_and_lender_are_cleaned():
    run_on = parse_notice("Commonly known as 20519 EXAMPLE LILAC LN SPRING, TX 77388\n")
    assert (run_on["street"], run_on["city"]) == ("20519 EXAMPLE LILAC LN", "Spring")
    misread = parse_notice("Property Address:\n15310 EXAMPLE PARK DRIVE. Humbt.E, TX 77396\n")
    assert (misread["street"], misread["city"]) == ("15310 EXAMPLE PARK DRIVE", "Humble")
    junk = parse_notice("Property Address: 951-1 11 7815 EXAMPLE MARIA TRAIL, Houston, TX 77044\n")
    assert junk["street"] == "7815 EXAMPLE MARIA TRAIL"
    office = parse_notice("Lender office: 20405 State Highway 249 Sute 170, Houston, TX 77070\n")
    assert office["street"] is None
    whose = parse_notice("the Note. EXAMPLE LOAN SERVICES, LLC, whose address is c/o Example Loan Services, LLC, PO Box\n"
                         "30597, Los Angeles, CA 90030, is the current mortgagee of the Deed of Trust and Note\n")
    assert whose["lender"] == "EXAMPLE LOAN SERVICES, LLC"


def test_lender_spans_lines_and_never_takes_the_borrower_sentence():
    assert lender("renewals and extensions of the promissory note. Carrington Mortgage\n"
                  "Services, LLC is the current mortgagee of the note and Deed of Trust.") == "Carrington Mortgage Services, LLC"
    assert lender("Deed of Trust or Contract Lien executed by JANE DOE SINGLE WOMAN, securing the\n"
                  "but not limited to the promissory note and all modifications, renewals and extensions of the\n"
                  "BANK is the current mortgagee of the note.") is None
    assert lender("Borrower: A Person\nLender:\nXuan Example\n") is None
