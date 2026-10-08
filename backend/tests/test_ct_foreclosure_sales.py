from datetime import date

from pipeline.load_ct_foreclosure_sales import address, parties, sale_status
from pipeline.scrape_ct_foreclosure_sales import notice_fields, town_sales


def test_address_with_zip_and_town():
    assert address("PUBLIC AUCTION FORECLOSURE SALE: ADDRESS: 65-73 Center Street Bridgeport, CT 06604", "Bridgeport") == (
        "65-73 Center Street", "Bridgeport", "06604")


def test_address_with_unit_and_no_zip():
    street, city, zip_code = address("PUBLIC AUCTION FORECLOSURE SALE: Residential ADDRESS: 2445 Park Avenue, Unit 13, Bridgeport, CT", "Bridgeport")
    assert (city, zip_code) == ("Bridgeport", None) and street.startswith("2445 Park Avenue")


def test_parties_and_status():
    assert parties("U.S. BANK NATIONAL ASSOCIATION  v. CAMPBELL, CHRISTOPHER Et Al") == (
        "U.S. BANK NATIONAL ASSOCIATION", "CAMPBELL, CHRISTOPHER Et Al")
    today = date(2026, 10, 8)
    assert sale_status("ADDRESS: 1 A St", date(2026, 10, 17), today) == "scheduled"
    assert sale_status("ADDRESS: 1 A St", date(2026, 10, 1), today) == "sold_or_cancelled_unverified"
    assert sale_status("CANCELLED - ADDRESS: 1 A St", date(2026, 10, 17), today) == "cancelled"


def test_town_page_and_notice_parsing():
    page = ('<table><tr><th>#</th></tr><tr><td>1</td><td>10/17/2026 12:00PM</td><td>FBTCV246135550S</td>'
            '<td>PUBLIC AUCTION FORECLOSURE SALE: ADDRESS: 65-73 Center Street Bridgeport, CT 06604</td>'
            '<td><a href="PendPostDetailPublic.aspx?PostingId=61625">View Full Notice</a></td></tr></table>')
    sale = town_sales(page)[0]
    assert (sale["posting_id"], sale["sale_date"], sale["docket"]) == ("61625", "10/17/2026 12:00PM", "FBTCV246135550S")
    notice = notice_fields("<div>Case Caption:</div><div>A v. B</div><div>TOWN:</div><div>Bridgeport</div>"
                           "<p>a certified check in the amount of $60,800.00</p>")
    assert (notice["Case Caption"], notice["TOWN"], notice["deposit"]) == ("A v. B", "Bridgeport", "60,800.00")


def test_lead_in_words_and_villages():
    from pipeline.ct_towns import county_for
    assert address("PUBLIC AUCTION FORECLOSURE SALE: Residential property 173 Puritan Road, Fairfield, CT 06824", "Fairfield") == (
        "173 Puritan Road", "Fairfield", "06824")
    assert address("SALE: 11/07/2026 ADDRESS: residential property 115 Shaker Road Enfield, CT 06082", "Enfield") == (
        "115 Shaker Road", "Enfield", "06082")
    assert county_for("Stafford Springs") == "Tolland" and county_for("Bridgeport") == "Fairfield"
