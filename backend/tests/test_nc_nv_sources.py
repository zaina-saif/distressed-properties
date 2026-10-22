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
