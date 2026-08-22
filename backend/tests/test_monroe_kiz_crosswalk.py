from datetime import date

from pipeline.import_monroe_kiz_crosswalk import assessment_row, parse_sale_date


def test_parse_sale_date_rejects_blank_and_invalid_values() -> None:
    assert parse_sale_date("02/06/2003") == date(2003, 2, 6)
    assert parse_sale_date(" ") is None
    assert parse_sale_date("invalid") is None


def test_assessment_row_builds_authoritative_crosswalk_and_total() -> None:
    row = assessment_row({
        "FID": 4,
        "MAPNUMBER": "05730220912442",
        "PARID": "05-6.1.1.7",
        "LANDVALUE": 112800,
        "BLDGVALUE": 91780,
        "PREFVALUE": 0,
        "IAS_TAXYEA": 2022,
        "SALEDATE": "02/06/2003",
    })
    assert row is not None
    assert row["normalized_tax_parcel_id"] == "05.6.1.1.7"
    assert row["assessed_value"] == 204580
    assert row["last_sale_date"] == date(2003, 2, 6)
