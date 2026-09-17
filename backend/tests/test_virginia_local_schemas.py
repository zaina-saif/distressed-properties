from decimal import Decimal

from pipeline.import_virginia_local_schemas import field_map, parse_sales, parse_snapshot


def test_virginia_standardized_snapshot_mapping() -> None:
    row = {"VGIN_QPID": 5102100000001, "Prop_Addr": "10 MAIN ST", "Class": "R",
           "LandValue": "50000", "BldgValue": "150000", "TotalValue": "200000"}
    parsed = parse_snapshot(row, field_map(list(row)), "Bland County")
    assert parsed is not None and parsed[3] == "51-5102100000001"
    assert parsed[5] == "10 MAIN ST" and parsed[8] == "R"
    assert parsed[16:19] == (Decimal("50000"), Decimal("150000"), Decimal("200000"))


def test_virginia_building_and_multiple_sales_mapping() -> None:
    row = {"VGIN_QPID": 1, "YearBuilt": "1998", "Bedrooms": "3", "FullBath": "2",
           "HalfBath": "1", "Sale1D": "05/01/2020", "Sale1Amt": "250000",
           "Sale2D": "2010-06-02", "Sale2Amt": "170000", "Owner": "excluded"}
    fields = field_map(list(row))
    parsed = parse_snapshot(row, fields, "Test County")
    sales = list(parse_sales(row, fields, "Test County"))
    assert parsed is not None and parsed[10] == 1998 and parsed[14:16] == (Decimal("3"), Decimal("2.5"))
    assert len(sales) == 2 and {item[6] for item in sales} == {Decimal("250000"), Decimal("170000")}


def test_virginia_snapshot_ignores_nan_numeric_values() -> None:
    row = {"VGIN_QPID": 1, "YEARBLT": float("nan"), "TOTALVALUE": float("nan")}
    parsed = parse_snapshot(row, field_map(list(row)), "Test County")
    assert parsed is not None and parsed[10] is None and parsed[18] is None


def test_virginia_snapshot_rejects_out_of_range_year() -> None:
    row = {"VGIN_QPID": 1, "YEARBLT": "99999"}
    parsed = parse_snapshot(row, field_map(list(row)), "Test County")
    assert parsed is not None and parsed[10] is None


def test_virginia_sales_reject_excel_missing_date_sentinel() -> None:
    row = {"VGIN_QPID": 1, "SaleDate": "01/01/1900", "SalePrice": "100000"}
    assert list(parse_sales(row, field_map(list(row)), "Test County")) == []
