from pipeline.load_ca_tax_sales import details, sales_by_county
from pipeline.scrape_ca_tax_sales import apn_of, location, storefront_info, storefront_paths

STOREFRONT = ('<title>Bid4Assets: County of Santa Clara, CA Tax Defaulted Properties Auction</title>'
              ' url: "/storefront/taxsales/getauctiondisplay/17855?storefrontCollectionId=" '
              '"Data":[{"StorefrontCollectionId":10532,"ParentStorefrontCollectionId":10257},'
              '{"StorefrontCollectionId":10533}]')


def test_california_storefronts_only_and_not_timeshares():
    info = storefront_info(STOREFRONT)
    assert info["county"] == "Santa Clara" and info["storefront_id"] == 17855
    assert info["collections"] == [10532, 10533]
    assert storefront_info(STOREFRONT.replace("County of Santa Clara, CA", "Nye County, NV")) is None
    timeshare = STOREFRONT.replace("County of Santa Clara, CA Tax Defaulted Properties",
                                   "El Dorado County, CA Tax Defaulted Timeshares")
    assert storefront_info(timeshare) is None
    assert storefront_info(STOREFRONT.replace("County of Santa Clara", "El Dorado County"))["county"] == "El Dorado"
    assert storefront_paths('<a href="/storefront/SantaClaraOct26">x</a><a href="/storefront/SantaClaraOct26">') == [
        "/storefront/SantaClaraOct26"]


def test_location_with_and_without_zip():
    page = "<div>Location:</div><div>889 Canada Dr</div><div>Milpitas, CA 95035</div><div>Share</div>"
    assert location(page) == ("889 Canada Dr", "Milpitas", "95035")
    assert location(page.replace("Milpitas, CA 95035", "TAMARACK, CA")) == ("889 Canada Dr", "Tamarack", None)
    assert location(page.replace("889 Canada Dr", "No Situs")) == (None, None, None)
    assert apn_of("County of Santa Clara, CA: 028-04-048") == "028-04-048"


def test_parcels_load_with_minimum_bid_and_details():
    parcel = {"case": "028-04-048", "auction_id": 1314108, "apn": "028-04-048", "sale_date": "2026-11-02",
              "opens": "2026-10-30T11:00:00", "closes": "2026-11-02T15:00:00", "minimum_bid": 54000,
              "street": "889 Canada Dr", "city": "Milpitas", "zip_code": "95035",
              "auction_url": "https://www.bid4assets.com/auction/index/1314108"}
    land = parcel | {"case": "999", "street": None, "city": None}
    sale = {"county": "Santa Clara", "title": "County of Santa Clara, CA Tax Defaulted Properties Auction",
            "url": "https://www.bid4assets.com/storefront/SantaClaraOct26", "parcels": [parcel, land]}
    [(county, (_, listings))] = sales_by_county({"sales": [sale]}).items()
    assert county == "Santa Clara" and [listing.case for listing in listings] == ["028-04-048"]
    assert listings[0].upset == 54000 and listings[0].status == "scheduled"
    text = details(parcel, sale)
    assert "Minimum bid: $54,000.00" in text and "closes November 2, 2026 at 3:00 PM ET" in text
