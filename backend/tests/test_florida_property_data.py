from datetime import date
from decimal import Decimal

from pipeline.import_florida_property_data import parse_nal, parse_sdf


def test_parse_florida_nal_maps_values_without_owner_fields() -> None:
    parsed = parse_nal({
        "CO_NO": "49", "PARCEL_ID": "0195S3W00001000", "ASMNT_YR": "2026",
        "DOR_UC": "087", "JV": "252000", "AV_NSD": "250000",
        "LND_VAL": "50000", "LND_SQFOOT": "12196800",
        "ACT_YR_BLT": "1990", "TOT_LVG_AREA": "2100",
        "PHY_ADDR1": "123 MAIN ST", "PHY_CITY": "HOSFORD", "PHY_ZIPCD": "32334",
        "OWN_NAME": "MUST NOT BE STORED",
    })
    assert parsed is not None
    assert parsed[2] == "Liberty"
    assert parsed[3] == "49:0195S3W00001000"
    assert parsed[11] == 2100
    assert parsed[15] == Decimal("202000")
    assert parsed[16] == Decimal("250000")
    assert parsed[17] == Decimal("252000")
    assert "MUST NOT BE STORED" not in parsed


def test_parse_florida_sdf_marks_qualified_sale() -> None:
    parsed = parse_sdf({
        "CO_NO": "49", "PARCEL_ID": "P-1", "SALE_ID_CD": "14698",
        "SALE_YR": "2026", "SALE_MO": "05", "SALE_PRC": "325000",
        "QUAL_CD": "01", "VI_CD": "I",
    })
    assert parsed is not None
    assert parsed[5] == date(2026, 5, 1)
    assert parsed[6] == Decimal("325000")
    assert parsed[8] is True


def test_parse_florida_sdf_rejects_nonpositive_sale() -> None:
    assert parse_sdf({
        "CO_NO": "49", "PARCEL_ID": "P-1", "SALE_YR": "2026",
        "SALE_MO": "05", "SALE_PRC": "0",
    }) is None
