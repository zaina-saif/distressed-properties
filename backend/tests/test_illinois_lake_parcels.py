from decimal import Decimal

from pipeline.import_illinois_lake_parcels import FIELDS, parse_feature


def test_maps_lake_situs_and_coordinates() -> None:
    parsed = parse_feature({"attributes":{"PIN":"17-31-302-057","situs_addr":"HIGHLAND PARK",
        "situs_ad_1":"40 S DEERE PARK DR","situs_ad_5":"60035","taxpayer_n":"excluded"},
        "geometry":{"x":-87.7609,"y":42.1524}})
    assert parsed[3] == "IL:LAKE:1731302057" and parsed[5:8] == ("40 S DEERE PARK DR","HIGHLAND PARK","60035")
    assert parsed[8:10] == (Decimal("-87.7609"), Decimal("42.1524"))


def test_taxpayer_fields_are_not_requested() -> None:
    assert not any("taxpayer" in field.lower() for field in FIELDS)
