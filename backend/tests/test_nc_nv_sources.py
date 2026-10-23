from datetime import date

from pipeline.load_nc_hutchens_sales import sales_by_county as hutchens_by_county
from pipeline.load_nc_zls_tax_foreclosures import sales_by_county as zls_by_county, status_of
from pipeline.scrape_ca_tax_sales import location, storefront_info
from pipeline.scrape_nc_hutchens_sales import sales_from
from pipeline.scrape_nc_zls_tax_foreclosures import parcel_from

HUTCHENS = """<table><tr><th>Case No.</th><th>SP#</th></tr>
<tr class="GridRow_WebBlue"><td>12723-55524</td><td>23SP000254-250</td><td>Cumberland, NC</td><td>10/26/2026</td>
<td>189 Wolfpoint Drive</td><td>Fayetteville, NC 28311</td><td>09458 / 0763</td><td>$214,328.00</td></tr>
<tr><td>2119-4575</td><td>20SP000066-730</td><td>Pitt, NC</td><td>11/4/2026</td><td>506 Lancelot Drive</td>
<td>Greenville, NC 27858</td><td>3167 / 3</td><td>Bid not available yet</td></tr>
<tr><td>6991-26473</td><td>22 SP 18</td><td>Avery, NC</td><td>2/8/2023</td><td>196 Old Turnpike Road East</td>
<td>Banner Elk, NC 28604</td><td>RE 481 / 2247</td><td>Bid not available yet</td></tr></table>"""


def test_hutchens_rows_become_sales_and_stale_dates_are_dropped():
    sales = sales_from(HUTCHENS, date(2026, 10, 22))
    assert [sale["case"] for sale in sales] == ["12723-55524", "2119-4575"]
    assert sales[0] == {"case": "12723-55524", "sp_number": "23SP000254-250", "county": "Cumberland",
                        "sale_date": "2026-10-26", "street": "189 Wolfpoint Drive", "city": "Fayetteville",
                        "zip_code": "28311", "deed_of_trust": "09458 / 0763", "opening_bid": "$214,328.00"}
    assert sales[1]["opening_bid"] is None
    counties = hutchens_by_county({"sales": sales})
    sale = counties["Cumberland"][0][1]
    assert sale.status == "scheduled_unverified" and sale.upset == 214328.0 and sale.property_number == "23SP000254-250"


ZLS_ROW = ["Chatham County Tax Office", "0019510", "Upset Bidding in Progress", "9/16/2026", "10/30/2026 5:00 PM",
           "n/a", "$42,997.50", "Notice", "⚠️ 3268 Farrington Point Rd, Chapel Hill, NC 27517"]


def test_zls_rows_read_counties_addresses_and_bids():
    parcel = parcel_from(ZLS_ROW)
    assert parcel["county"] == "Chatham" and parcel["sale_date"] == "2026-09-16"
    assert (parcel["street"], parcel["city"], parcel["zip_code"]) == ("3268 Farrington Point Rd", "Chapel Hill", "27517")
    assert parcel["opening_bid"] is None and parcel["current_bid"] == "$42,997.50"
    town = parcel_from(["City of Laurinburg", "123", "Courthouse Sale", "11/5/2026", "n/a", "$1,000.00", "n/a",
                        "Notice", ""])
    assert town["county"] == "Scotland" and town["street"] is None


def test_zls_statuses():
    upset = parcel_from(ZLS_ROW)
    assert status_of(upset)[:2] == ("scheduled", date(2026, 10, 30)) and status_of(upset)[3] == 42997.5
    sale = {**upset, "status": "Courthouse Sale", "upset_deadline": None, "opening_bid": "$9,000.00",
            "current_bid": None, "sale_date": "2026-11-05"}
    assert status_of(sale) == ("scheduled", date(2026, 11, 5), "courthouse sale", 9000.0)
    assert status_of({**sale, "status": "Sale Confirmed", "current_bid": "$45,000.00"})[0] == "sold"
    assert status_of({**sale, "status": "Redeemed"})[0] == "redeemed"
    assert status_of({**sale, "status": "Something New"}) is None
    counties, unknown = zls_by_county({"parcels": [upset, {**sale, "status": "Something New"}]})
    assert list(counties) == ["Chatham"] and len(unknown) == 1


def test_bid4assets_reads_nevada_tax_sales_only():
    page = ('<title>Bid4Assets: Nye County, NV Tax Defaulted Properties Auction</title>'
            'getauctiondisplay/123 "StorefrontCollectionId":9990')
    assert storefront_info(page, "NV")["county"] == "Nye"
    assert storefront_info(page) is None  # not a California sale
    assert storefront_info(page.replace("Tax Defaulted Properties Auction", "Public Works Special Sale"), "NV") is None
    auction = "<div>Location:</div><div>101 Main St</div><div>Pahrump, NV 89048</div>"
    assert location(auction, "NV") == ("101 Main St", "Pahrump", "89048")


def test_clark_parcels_drop_the_owner_and_get_a_city():
    from pipeline.scrape_nv_clark_tax_auction import apn, city_of, parcel_from

    row = {"ParcelNumber": "124-32-611-028", "MinBidAmount": 6780.64, "Owner": "SOMEONE", "PropertyLocation":
           "2603 BRAVE HEART AVE", "IsLineOut": True, "WinningBidAmount": 0.0, "DeedRecordingDate": None}
    places = {"12432611028": {"city": "North Las Vegas", "zip_code": "89031", "latitude": 36.25, "longitude": -115.18}}
    parcel = parcel_from(row, places)
    assert "SOMEONE" not in str(parcel) and apn(row["ParcelNumber"]) == "12432611028"
    assert parcel["street"] == "2603 Brave Heart Ave" and parcel["city"] == "North Las Vegas" and not parcel["winning_bid"]
    assert parcel_from({**row, "PropertyLocation": "UNASSIGNED SITUS"}, places)["street"] is None
    assert city_of("SPRV", "89148") == "Las Vegas" and city_of("CNTY", "89040") == "Overton" and city_of("CNTY", "76050") is None


def test_clark_statuses_before_and_after_the_auction():
    from pipeline.load_nv_clark_tax_auction import status_of

    day, parcel = date(2026, 5, 7), {"struck": False, "winning_bid": None}
    assert status_of(parcel, day, date(2026, 5, 1))[0] == "scheduled"
    assert status_of({**parcel, "struck": True}, day, date(2026, 5, 1))[0] == "cancelled"
    assert status_of({"struck": True, "winning_bid": 1537.13}, day, date(2026, 6, 1))[0] == "sold"
    assert status_of({**parcel, "struck": True}, day, date(2026, 6, 1))[0] == "cancelled"
    assert status_of(parcel, day, date(2026, 6, 1))[0] == "unsold"


def test_georgia_parcel_ids_and_list_dates():
    from pipeline.scrape_ga_tax_sales import cobb_id, fulton_id, posting_rank, sale_date_of

    assert fulton_id("06-0356-0004-007-8") == "06 035600040078"
    assert fulton_id("13-0127-LL-018-4") == "13 0127  LL0184"
    assert fulton_id("09F-1709-0067-060-1") == "09F170900670601"
    assert fulton_id("11- 0261-0119-011-6") == "11 026101190116" and fulton_id("1126-57775") is None
    assert cobb_id("16-0011-0-155-0") == "16001101550" and cobb_id("16-0011") is None
    cobb = [(1, 0.01, 0.83, 0.01, "OCT 20, 2026"), (1, 0.41, 0.85, 0.01, "TAX SALE STARTING BIDS NOV-2026")]
    assert sale_date_of(cobb) == date(2026, 11, 3)
    assert sale_date_of([(1, 0.26, 0.9, 0.01, "NOVEMBER 3, 2026, SHERIFF'S TAX / LEVY SALE")]) == date(2026, 11, 3)
    assert posting_rank("/Sheriffs-August-4-2026-Levy-Sale-List--2nd-Posting.pdf") == 2
    assert posting_rank("/FCSO-November-3-2026-Sale-List--1st-Posting.pdf") == 1


def test_georgia_rows_are_rebuilt_by_height_without_the_owner():
    from pipeline.scrape_ga_tax_sales import COUNTIES, rows_from

    boxes = [(1, 0.01, 0.7744, 0.011, "MITTLEIDER DOUGLAS K"), (1, 0.2306, 0.7744, 0.011, "16-0011-0-155-0"),
             (1, 0.3578, 0.7744, 0.011, "727 FARMDALE WAY"), (1, 0.8534, 0.7744, 0.011, "4,015.06 Residential"),
             (1, 0.2306, 0.7521, 0.011, "16-0011-0-157-0"), (1, 0.3578, 0.7521, 0.011, "723"),
             (1, 0.3901, 0.7521, 0.011, "FARMDALE wAY"), (1, 0.8534, 0.7521, 0.011, "4,015.06 Residential")]
    rows = rows_from(boxes, COUNTIES["Cobb"])
    assert [row["parcel_printed"] for row in rows] == ["16-0011-0-155-0", "16-0011-0-157-0"]
    assert rows[0]["street"] == "727 FARMDALE WAY" and rows[0]["starting_bid"] == "4,015.06 Residential"
    assert "MITTLEIDER" not in str(rows) and rows[1]["street"] == "723 FARMDALE wAY"


def test_dekalb_rows_skip_owner_tenant_and_defendant():
    from pipeline.scrape_ga_dekalb_tax_sales import parcel_from, rows

    cells = ["03-NOV-2026", "12 253 02 012", "12 253 02 012", "26-R30266532-NOV", "OWNER NAME", "4804 FLAKES MILL RD",
             "TENANT NAME", "DEFENDANT NAME", "DEK", "2919", "0357", "11-SEP-26", " 2025", " 2025", "$7,210.66"]
    page = "<table><tr><td>Tax Sale Date</td></tr><tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr></table>"
    listed = rows(page)
    assert len(listed) == 1 and "NAME" not in str(listed)
    place = {"street": "4804 Flakes Mill Road", "city": "Ellenwood", "zip_code": "30294", "latitude": 33.6, "longitude": -84.2}
    parcel = parcel_from(listed[0], place)
    assert parcel["sale_date"] == "2026-11-03" and parcel["starting_bid"] == 7210.66 and parcel["city"] == "Ellenwood"
    assert parcel_from(listed[0], None)["matched_by"] is None


def test_kane_and_will_lists():
    from pipeline.scrape_il_kane_sheriff_sales import sales_from as kane_sales, split_town
    from pipeline.scrape_il_will_sheriff_sales import sales_from as will_sales

    assert split_town("278 B WHITFIELD DR Sugar Grove") == ("278 B WHITFIELD DR", "Sugar Grove")
    assert split_town("703 S 7TH AVE St Charles") == ("703 S 7TH AVE", "St. Charles")
    assert split_town("12 MAIN ST South Elgin") == ("12 MAIN ST", "South Elgin")
    text = "11/5/2026 25FC627 26SCH198 560 BIRD STREET Elgin 37,794.99 1/2/2020 20FC1 20SCH1 1 OLD RD Aurora 1.00"
    sales = kane_sales(text, date(2026, 10, 23))
    assert [s["sheriff_number"] for s in sales] == ["26SCH198"] and sales[0]["judgment"] == 37794.99
    page = ("<tr><td>25 FC 1342-0</td><td>2069 Sunrise Cir</td><td>AURORA</td><td>11-05-2026</td><td>181,300.00</td></tr>"
            "<tr><td>25 FC 0821-0</td><td>455 Greenbriar Dr</td><td>Crete</td><td>11-05-2026</td><td>0.00</td></tr>")
    will = will_sales(page, date(2026, 10, 23))
    assert will[0]["opening_bid"] is None and will[1]["opening_bid"] == 181300.0 and will[1]["city"] == "Aurora"


def test_delaware_rows_by_position_skip_names():
    from pipeline.scrape_pa_delaware_sheriff_sales import rows_from

    lines = [(1, 78, [(40, "1."), (212, "Yeadon"), (406, "24-002351"), (487, "SOMEONE NAMED"), (705, "$38,491.35"),
                      (808, "Parker McCay PA")]),
             (1, 93, [(212, "910 W Cobbs Creek Parkway,,"), (705, "$3,849.14")]),
             (1, 108, [(40, "CONTINUED TO DECEMBER 18 2026 (1/30)")]),
             (1, 135, [(40, "2."), (212, "Upper Darby Twp."), (406, "26-001704"), (487, "OTHER NAME"),
                       (705, "$143,512.78"), (808, "Purcell Krug & Haller")]),
             (1, 147, [(212, "5138 Whitehall Drive,")]),
             (1, 160, [(40, "STAYED")])]
    rows = rows_from(lines, date(2026, 11, 20))
    assert "NAME" not in str(rows)
    assert rows[0]["street"] == "910 W Cobbs Creek Parkway" and rows[0]["sale_date"] == date(2026, 12, 18)
    assert rows[0]["status"] == "scheduled" and rows[0]["debt"] == 38491.35
    assert rows[1]["city"] == "Upper Darby" and rows[1]["status"] == "stayed"


def test_allegheny_ward_suffixes_and_statuses():
    from pipeline.scrape_pa_allegheny_sheriff_sales import WARD, status_of

    assert WARD.sub("", "5415 Butler Street - 10TH") == "5415 Butler Street"
    assert WARD.sub("", "227 MARLAND ST 30TH WARD") == "227 MARLAND ST"
    assert WARD.sub("", "229 Thornberry Drive -") == "229 Thornberry Drive"
    assert WARD.sub("", "100 1ST ST") == "100 1ST ST"
    assert status_of("Postponed to 5/3/2027", date(2026, 11, 2)) == ("scheduled", date(2027, 5, 3))
    assert status_of("Active", date(2026, 11, 2)) == ("scheduled", date(2026, 11, 2))
    assert status_of("Stayed", date(2026, 11, 2))[0] == "stayed"


def test_pima_notice_addresses():
    from pipeline.scrape_az_pima_sheriff_sales import notice_from

    one_line = ("judgment sum of $7,590.98, plus\n1984 West Nava Drive Tucson, AZ, 85746 Property Location:\n"
                "on the 3rd day of November, 2026 at 10:01 AM WRIT OF SPECIAL EXECUTION issued by")
    two_lines = "PAGE 59.\n4698 W. Beeplant Wy\nTucson, AZ 85741\nProperty Location:\non the 3rd day of December, 2026"
    first, second = notice_from(one_line), notice_from(two_lines)
    assert (first["street"], first["city"], first["zip_code"]) == ("1984 West Nava Drive", "Tucson", "85746")
    assert first["sale_date"] == "2026-11-03" and first["judgment"] == 7590.98
    assert (second["street"], second["zip_code"], second["sale_date"]) == ("4698 W. Beeplant Wy", "85741", "2026-12-03")


def test_tarrant_monthly_pages_and_rows():
    from pipeline.scrape_tx_tarrant_tax_sales import accounts_from, month_pages

    index = ('<a href="/en/constables/constable-3/delinquent-tax-sales/monthly-tax-sales-listings/october-6--2026.html">'
             '<a href="/en/constables/constable-3/delinquent-tax-sales/monthly-tax-sales-listings/november-3--2026.html">')
    assert [day for _, day in month_pages(index, date(2026, 10, 23))] == [date(2026, 11, 3)]
    page = ("<tr><td>CAUSE NUMBER</td><td>ACCOUNT NUMBER</td><td>STATUS</td></tr>"
            "<tr><td>D37745-23</td><td>00862274</td><td>For Sale</td></tr>"
            "<tr><td>D37745-23</td><td>60370998</td><td>For Sale Royalty&nbsp; Interest only</td></tr>"
            "<tr><td>D38909-23</td><td>01645315</td><td>Withdrawn</td></tr>")
    assert accounts_from(page) == [{"cause": "D37745-23", "account": "00862274", "status": "For Sale"}]
