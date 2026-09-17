from decimal import Decimal

from pipeline.import_ohio_property_data import parse_parcel


def test_parse_ohio_parcel_maps_public_fields() -> None:
    parsed = parse_parcel({
        "County": "Franklin", "LocalParcelID": "010-042534",
        "StateParcelID": "39049-010-042534", "StateLUC": "510: Res-Single Family",
        "SitusAddressAll": "84 W DODRIDGE ST", "LandArea": 0.25,
        "OwnerAll": "MUST NOT BE STORED", "MailAddressAll": "ALSO PRIVATE",
    })
    assert parsed is not None
    assert parsed[2] == "Franklin"
    assert parsed[3] == "39049-010-042534"
    assert parsed[5] == "84 W DODRIDGE ST"
    assert parsed[8] == Decimal("0.25")
    assert "MUST NOT BE STORED" not in parsed
    assert "ALSO PRIVATE" not in parsed


def test_parse_ohio_parcel_falls_back_to_county_local_id() -> None:
    parsed = parse_parcel({"County": "Adams", "LocalParcelID": "A-1"})
    assert parsed is not None
    assert parsed[3] == "Adams:A-1"


def test_parse_ohio_parcel_requires_identity() -> None:
    assert parse_parcel({"County": "Adams"}) is None
