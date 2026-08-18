from pipeline.normalize import normalize_address


def test_normalize_address_extracts_property_identity() -> None:
    result = normalize_address(
        "1001 2nd Avenue Unit 112 Asbury Park NJ 07712"
    )

    assert result.street_address == "1001 2Nd Avenue"
    assert result.unit_number == "112"
    assert result.city == "Asbury Park"
    assert result.state == "NJ"
    assert result.zip_code == "07712"
    assert result.needs_manual_review is False
    assert len(result.address_hash) == 64


def test_normalize_address_flags_missing_zip() -> None:
    result = normalize_address("180 Bernard Drive Red Bank NJ")

    assert result.needs_manual_review is True
    assert result.review_reason == "ZIP code missing"
    assert result.data_quality_score == 65
