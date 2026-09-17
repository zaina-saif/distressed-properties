from decimal import Decimal

from pipeline.import_virginia_fairfax_dta import parse_sale, parse_snapshot


def test_fairfax_snapshot_maps_assessment_and_dwelling() -> None:
    parsed = parse_snapshot({"PARID": "0083 11 0001", "TAXYR": 2026, "APRLAND": 200000,
                             "APRBLDG": 500000, "APRTOT": 700000},
                            {"LOCATION_DESC": "10 MAIN ST", "LUC_DESC": "Single Family"},
                            {"style": "Colonial", "year": 1995, "area": 2400,
                             "beds": Decimal(4), "baths": Decimal("2.5"), "updated": None},
                            {"acres": Decimal("0.25"), "sf": 0, "code": "Residential"})
    assert parsed is not None and parsed[3] == "51059-0083 11 0001"
    assert parsed[5:9] == ("10 MAIN ST", "Colonial", "Single Family", 1995)
    assert parsed[14:18] == (Decimal("200000"), Decimal("500000"), Decimal("700000"), Decimal("700000"))


def test_fairfax_valid_sale_mapping() -> None:
    parsed = parse_sale({"PARID": "0083 11 0001", "SALEDT": 1577836800000, "PRICE": 615000,
                         "BOOK": "12345", "PAGE": "9876", "SALEVAL_DESC": "Valid and verified sale"})
    assert parsed is not None and parsed[4] == "12345:9876"
    assert parsed[6] == Decimal("615000") and parsed[8] is True
