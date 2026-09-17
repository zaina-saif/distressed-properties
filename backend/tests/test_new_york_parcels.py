from decimal import Decimal

from pipeline.import_new_york_parcels import COLUMNS, FIELDS, parse


def test_parse_official_ny_parcel_fields_and_identity() -> None:
    attributes = {
        "COUNTY_NAME": "Albany", "MUNI_NAME": "Albany", "SWIS": "010100",
        "PRINT_KEY": "40.12-2-6.-68", "ROLL_YR": 2025,
        "LOC_ST_NBR": "15", "LOC_STREET": "MAIN ST", "LOC_ZIP": "12207",
        "PROP_CLASS": "210", "YR_BLT": 1974, "SQFT_LIVING": 1431.0,
        "NBR_BEDROOMS": 3, "NBR_FULL_BATHS": 1,
        "ACRES": 0.25, "LAND_AV": 50000, "TOTAL_AV": 200000,
    }
    row = parse(attributes)
    assert row is not None
    mapped = dict(zip(COLUMNS, row))
    assert mapped["source_parcel_id"] == "NY:010100:40122668"
    assert mapped["snapshot_year"] == 2025
    assert mapped["bedrooms"] == Decimal("3")
    assert mapped["bathrooms"] == Decimal("1")
    assert mapped["living_area"] == 1431
    assert mapped["year_built"] == 1974
    assert mapped["improvement_value"] == Decimal("150000")
    assert not any("OWNER" in name or "MAIL" in name for name in FIELDS)


def test_missing_and_invalid_features_are_not_fabricated() -> None:
    row = parse({"COUNTY_NAME": "Albany", "SWIS": "010100", "PRINT_KEY": "41-2-3",
                 "ROLL_YR": 2025, "SQFT_LIVING": 0, "YR_BLT": 2099,
                 "NBR_BEDROOMS": None, "NBR_FULL_BATHS": -1})
    assert row is not None
    mapped = dict(zip(COLUMNS, row))
    assert all(mapped[name] is None for name in ("living_area", "year_built", "bedrooms", "bathrooms"))
    assert parse({"COUNTY_NAME": "Albany", "ROLL_YR": 2025}) is None


def test_nyc_sbl_uses_existing_bbl_identity() -> None:
    row = parse({"COUNTY_NAME": "Bronx", "SBL": "2056490001", "ROLL_YR": 2025,
                 "PARCEL_ADDR": "2131 HART STREET", "SQFT_LIVING": 25500, "YR_BLT": 1912})
    assert row is not None
    mapped = dict(zip(COLUMNS, row))
    assert mapped["source_parcel_id"] == "NYC:BBL:2056490001"
    assert mapped["county"] == "Bronx"
    assert mapped["street_address"] == "2131 HART STREET"
    row = parse({"COUNTY_NAME": "NewYork", "SBL": "1000010001", "ROLL_YR": 2025})
    assert row is not None and dict(zip(COLUMNS, row))["county"] == "New York"
