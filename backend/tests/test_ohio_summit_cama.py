from decimal import Decimal

from pipeline.import_ohio_summit_cama import aggregate_dwellings, parse_sale, parse_snapshot


def test_summit_dwelling_uses_documented_bed_bath_and_area_fields() -> None:
    result = aggregate_dwellings(iter([
        {"PARCEL": "0100002", "BD": "3", "BTH": "1", "FXH": "1", "SFLA": "1040", "YRBLT": "1965"},
        {"PARCEL": "0100002", "BD": "1", "BTH": "1", "FXH": "0", "SFLA": "500", "YRBLT": "2000"},
    ]))["39153-0100002"]
    assert result == {"beds": Decimal("4"), "baths": Decimal("2.5"), "area": 1540, "year": 1965}


def test_summit_snapshot_maps_values_and_address() -> None:
    parsed = parse_snapshot(
        {"PARCEL": "0100002", "ADRNO": "860", "ADRDIR": "N", "ADRSTR": "SUMMIT", "ADRSUF": "ST",
         "CITY": "BARBERTON", "ZIPCD": "44203", "CLASS": "R", "LUC": "510"},
        {"beds": 3, "baths": Decimal("1.5"), "area": 1040, "year": 1965},
        {"APRLAND": "24080", "APRBLDG": "75090"},
        {"APRLAND": "68800", "APRBLDG": "214540", "COSTVAL": "283340"}, Decimal(".1197"),
    )
    assert parsed is not None and parsed[3] == "39153-0100002"
    assert parsed[5] == "860 N SUMMIT ST" and parsed[10:16] == (1965, 1040, Decimal(".1197"), "acres", 3, Decimal("1.5"))
    assert parsed[16:20] == (Decimal("68800"), Decimal("214540"), Decimal("99170"), Decimal("283340"))


def test_summit_sale_excludes_party_names_and_maps_history() -> None:
    parsed = parse_sale({"PARCEL": "0100001", "TRANSNO": "17447", "SALEDATE": "30-DEC-2010",
                         "PRICE": "40000", "SOURCECODE": "5", "SALEVAL": "J",
                         "OLDOWN": "excluded", "OWN1": "excluded"})
    assert parsed is not None and parsed[4] == "17447" and parsed[6] == Decimal("40000")
    assert parsed[8] == "5;J" and parsed[9] is None


def test_summit_sale_rejects_impossible_dates() -> None:
    assert parse_sale({"PARCEL": "0100001", "SALEDATE": "19-JUN-0097", "PRICE": "40000"}) is None
    assert parse_sale({"PARCEL": "0100001", "SALEDATE": "20-FEB-2104", "PRICE": "40000"}) is None
