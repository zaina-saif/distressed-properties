from datetime import date

from pipeline.load_sri_sales import status, to_sale
from pipeline.sale_results import parse_sale_result

TODAY = date(2026, 10, 10)


def item(status_text="Sale Active", auction_date="01/21/2027", price="$0.00", minimum="Pending"):
    return {
        "listing": {
            "id": 132897, "propertyId": "71-09-17-480-014.000-023", "address1": "909 Hendricks Street",
            "city": "MIshawaka", "zip": "46544-1234", "auctionDate": auction_date,
            "saleStatusDescription": status_text, "displaySaleId": "71D05-2601-MF-000005",
            "latitude": 41.65311186442, "longitude": -86.2000883500681, "briefLegal": "Addis, Benjamin",
        },
        "detail": {"propertyInfo": {
            "causeNumber": "71D05-2601-MF-000005", "defendant": "Addis, Benjamin",
            "plantiff": "UNITED WHOLESALE MORTGAGE, LLC.", "attorney": "Reisenfeld & Associates",
            "judgementAmount": "$143267.75", "minimumBid": minimum, "status": status_text, "salePrice": price,
        }},
    }


def test_upcoming_listing_becomes_a_scheduled_sale():
    sale = to_sale(item(), TODAY)

    assert sale.case == "71D05-2601-MF-000005:71-09-17-480-014.000-023"
    assert (sale.street, sale.city, sale.zip_code) == ("909 Hendricks Street", "Mishawaka", "46544")
    assert sale.sale_date == date(2027, 1, 21)
    assert sale.status == "scheduled"
    assert sale.judgment == 143267.75
    assert sale.upset is None  # "Pending"
    assert sale.plaintiff == "UNITED WHOLESALE MORTGAGE, LLC."
    assert round(sale.latitude, 2) == 41.65


def test_sold_listing_carries_price_and_buyer_for_sale_results():
    sale = to_sale(item("Sold To 3rd Party", "01/15/2026", "$81,500.00", "$95,000.00"), TODAY)

    assert sale.status == "sold"
    assert sale.upset == 95000
    result = parse_sale_result(None, [sale.raw_status], sale.sale_date)
    assert result.buyer == "third_party"
    assert float(result.amount) == 81500


def test_statuses():
    assert status("Sold To Plaintiff", date(2026, 1, 1), TODAY) == "sold"
    assert status("Cancelled", date(2026, 1, 1), TODAY) == "cancelled"
    assert status("Sale Active", date(2026, 1, 1), TODAY) == "sold_or_cancelled_unverified"
    assert status("Sale Active", date(2026, 11, 1), TODAY) == "scheduled"


def test_street_line_drops_a_repeated_city_line():
    data = item()
    data["listing"]["address1"] = "19548 Yoder St\r\nSouth Bend, Indiana 46614-5540"
    data["listing"]["latitude"] = 0
    sale = to_sale(data, TODAY)
    assert sale.street == "19548 Yoder St"
    assert sale.latitude is None  # outside Indiana


def test_street_line_drops_a_comma_separated_city_and_state():
    data = item()
    data["listing"]["address1"] = "1607 Etna Avenue, Huntington, Indiana, 46750"
    assert to_sale(data, TODAY).street == "1607 Etna Avenue"
