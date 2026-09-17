from pipeline.import_ohio_cuyahoga_cama import parse_sale, parse_snapshot


ROW = {
    "PARCEL_ID": "00101004", "PARCEL_YEAR": 2026, "TAX_YEAR": 2025,
    "TRANSFER_DATE": 1173330000000, "SALES_AMOUNT": 292000,
    "PAR_ADDR": "11601", "PAR_STREET": "HARBORVIEW", "PAR_SUFFIX": "DR",
    "PAR_CITY": "CLEVELAND", "PAR_ZIP": "44102", "TAX_LUC": "5100",
    "TAX_LUC_DESCRIPTION": "1-FAMILY PLATTED LOT", "TOTAL_RES_LIV_AREA": 2537,
    "TOTAL_ACREAGE": 0.3031, "CERTIFIED_TAX_LAND": 129700,
    "CERTIFIED_TAX_BUILDING": 417300, "CERTIFIED_TAX_TOTAL": 547000,
    "PARCEL_OWNER": "MUST NOT BE STORED", "GRANTEE": "PRIVATE",
}


def test_cuyahoga_snapshot_maps_assessment_without_names() -> None:
    parsed = parse_snapshot(ROW)
    assert parsed is not None and parsed[3] == "39035-00101004"
    assert parsed[4] == 2025 and parsed[10] == 2537
    assert "MUST NOT BE STORED" not in parsed and "PRIVATE" not in parsed


def test_cuyahoga_sale_maps_latest_transfer() -> None:
    parsed = parse_sale(ROW)
    assert parsed is not None and parsed[3] == "39035-00101004"
    assert parsed[6] == 292000
