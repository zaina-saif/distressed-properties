from decimal import Decimal

from pipeline.import_illinois_madison_parcels import FIELDS, parse


def test_madison_mapping_and_privacy() -> None:
    row = parse({"PIN": "07-1-11-02-00-000-002", "NUM": "11408", "ST_NAME": "LUESCHER",
                 "ST_TYPE": "RD", "CITY": "ALHAMBRA", "ZIP": "62001",
                 "SQFT": 878584.04, "ACRES": 20.17})
    assert row[3] == "IL:MADISON:071110200000002"
    assert row[5:8] == ("11408 LUESCHER RD", "ALHAMBRA", "62001")
    assert row[8:10] == (Decimal("878584.04"), "square feet")
    assert not any("own" in field.lower() or "mail" in field.lower() for field in FIELDS)
