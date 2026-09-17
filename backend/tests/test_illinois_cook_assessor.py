from datetime import date
from decimal import Decimal

from pipeline.import_illinois_cook_assessor import FEEDS, parse_assessment, parse_characteristic, parse_sale


def test_assessment_prefers_board_values() -> None:
    row = {"pin":"01011000430000","year":"2025","class":"203","mailed_tot":"3000",
           "certified_tot":"3200","board_land":"1000","board_bldg":"2400","board_tot":"3400"}
    parsed = parse_assessment(row)
    assert parsed[3] == "IL:COOK:01011000430000" and parsed[4] == 2025
    assert parsed[18:21] == (Decimal("1000"), Decimal("2400"), Decimal("3400"))


def test_house_characteristics_include_half_baths() -> None:
    row = {"pin":"01011000430000","year":"2025","class":"203","char_yrblt":"1935",
           "char_bldg_sf":"1366","char_land_sf":"8712","char_beds":"2","char_fbath":"1","char_hbath":"1",
           "char_type_resd":"1 Story"}
    parsed = parse_characteristic(row)
    assert parsed[12:18] == (1935, 1366, Decimal("8712"), "square feet", Decimal("2"), Decimal("1.5"))


def test_filtered_sale_is_not_arms_length() -> None:
    row = {"pin":"01011000430000","sale_date":"2023-01-12","sale_price":"100000","row_id":"1",
           "deed_type":"Warranty","sale_filter_less_than_10k":"false","sale_filter_deed_type":"true"}
    parsed = parse_sale(row)
    assert parsed[5] == date(2023,1,12) and parsed[7] == Decimal("100000") and parsed[9] is False


def test_no_identity_fields_are_requested() -> None:
    fields = {field for _, columns, _, _, _ in FEEDS.values() for field in columns}
    assert not fields & {"seller_name","buyer_name","owner_address_name","mail_address_name","owner_address_full","mail_address_full"}
