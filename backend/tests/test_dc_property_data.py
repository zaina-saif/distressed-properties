from datetime import date
from decimal import Decimal

from pipeline.import_dc_property_data import (
    arcgis_date,
    cama_characteristics,
    normalize_ssl,
    parse_sale,
    parse_snapshot,
)


def test_normalize_ssl_collapses_fixed_width_spaces() -> None:
    assert normalize_ssl("0025    2143") == "0025 2143"


def test_cama_characteristics_combines_half_bathrooms() -> None:
    item = cama_characteristics({
        "SSL": "0150    0093", "BEDRM": 3, "BATHRM": 1,
        "HF_BATHRM": 1, "AYB": 1900, "GBA": 900, "LANDAREA": 827,
        "USECODE": 11,
    }, "Residential")
    assert item is not None
    assert item["bathrooms"] == Decimal("1.5")
    assert item["living_area"] == 900


def test_parse_dc_snapshot_excludes_identity_fields_and_maps_values() -> None:
    snapshot = parse_snapshot({
        "SSL": "0150    0093", "PROPTYPE": "Residential-True",
        "USECODE": "011", "LANDAREA": 827,
        "PREMISEADD": "123 MAIN ST NW WASHINGTON DC 20001",
        "NEWLAND": 300000, "NEWIMPR": 450000, "NEWTOTAL": 750000,
        "EXTRACTDAT": 1788912000000,
    }, {"year_built": 1900, "living_area": 900, "bedrooms": Decimal(3),
        "bathrooms": Decimal("1.5"), "updated": None})
    assert snapshot is not None
    assert snapshot.source_parcel_id == "0150 0093"
    assert snapshot.zip_code == "20001"
    assert snapshot.total_assessed_value == Decimal("750000")
    assert snapshot.living_area == 900


def test_parse_dc_sale_maps_qualified_indicator() -> None:
    sale = parse_sale({
        "OBJECTID": 488709956, "SSL": "0025    2143",
        "SALE_DATE": 1125979200000, "SALE_PRICE": 645900,
        "QUALIFIED": "Q        ", "SALE_CODE": "01",
    })
    assert sale is not None
    assert sale.sale_date == date(2005, 9, 6)
    assert sale.arms_length is True
    assert sale.sale_price == Decimal("645900")


def test_parse_dc_sale_skips_zero_price() -> None:
    assert parse_sale({"OBJECTID": 1, "SSL": "1 1", "SALE_DATE": 1, "SALE_PRICE": 0}) is None
