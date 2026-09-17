from datetime import datetime

from pipeline.import_nyc_staten_island_sales import parse_row


def sample_row(**overrides):
    row = {
        "BOROUGH": "5", "BLOCK": 5391, "LOT": 11, "SALEPRICE": 800000,
        "SALEDATE": datetime(2025, 2, 27), "ADDRESS": "4720 AMBOY ROAD",
        "APARTMENTNUMBER": "", "BUILDINGCLASSATTIMEOFSALE": "A5",
        "BUILDINGCLASSCATEGORY": "01 ONE FAMILY DWELLINGS",
        "BUILDINGCLASSATPRESENT": "A5", "ZIPCODE": 10312,
        "YEARBUILT": 2002, "GROSSSQUAREFEET": 910, "LANDSQUAREFEET": 2880,
    }
    row.update(overrides)
    return row


def test_parse_row_maps_sale_and_features():
    sale, snapshot = parse_row(sample_row())
    assert sale[2:7] == ("Richmond", "NYC:BBL:5053910011", sale[4], datetime(2025, 2, 27).date(), 800000)
    assert snapshot[3:6] == ("NYC:BBL:5053910011", 2025, "4720 AMBOY ROAD")
    assert snapshot[6:13] == ("10312", "01 ONE FAMILY DWELLINGS", "A5", 2002, 910, 2880, "sqft")


def test_parse_row_rejects_zero_price_and_other_borough():
    assert parse_row(sample_row(SALEPRICE=0)) is None
    assert parse_row(sample_row(BOROUGH="4")) is None


def test_transaction_identity_is_stable_for_annual_and_rolling():
    first, _ = parse_row(sample_row())
    second, _ = parse_row(sample_row())
    assert first[4] == second[4]
