from datetime import datetime
from decimal import Decimal

from pipeline.import_virginia_richmond_assessor import parse_sale, parse_snapshots


def test_richmond_maps_five_assessment_years_without_historical_feature_leakage() -> None:
    row = {"PIN": "C0010124002", "PARCEL_LOCATION": "8536 Riverside Dr", "PROP_TYPE": "Residential",
           "PRIMARY_USE": "Single Family", "YEAR_BUILT": 2024, "LIVING_AREA": 1800,
           "BED_COUNT": 3, "BATH_COUNT": 2, "HALF_BATH_COUNT": 1, "LEGAL_AC": .25}
    for position, year in enumerate(range(2026, 2021, -1), 1):
        row[f"ASSESSMENT_DATE_{position}"] = datetime(year, 1, 1)
        row[f"ASSSESS_LAND_VALUE_{position}"] = 100000
        row[f"ASSSESS_IMP_VALUE_{position}"] = 200000
        row[f"ASSSESS_TOTAL_VALUE_{position}"] = 300000
    parsed = list(parse_snapshots(row))
    assert len(parsed) == 5 and parsed[0][3] == "51760-C0010124002"
    assert parsed[0][10:16] == (2024, 1800, Decimal("0.25"), "acres", Decimal("3"), Decimal("2.5"))
    assert parsed[1][10] is None and parsed[1][11] is None and parsed[1][14] is None


def test_richmond_qualified_sale() -> None:
    parsed = parse_sale({"PIN": "C0010124002", "TRANSFER_DATE": datetime(2020, 5, 1),
                         "CONSIDERATION": 250000, "DEED_BOOK": "ID2020", "DEED_PAGE": 42,
                         "SALE_TYPE": "S", "DEED_TYPE": "BS", "QUALIFIED": "Q", "GRANTEE": "excluded"})
    assert parsed is not None and parsed[4] == "ID2020:42"
    assert parsed[6] == Decimal("250000") and parsed[8] is True


def test_richmond_rejects_assessment_dates_outside_published_window() -> None:
    row = {"PIN": "C0010124002", "ASSESSMENT_DATE_1": datetime(2005, 1, 1),
           "ASSSESS_TOTAL_VALUE_1": 100000}
    assert list(parse_snapshots(row)) == []
