from pipeline.parcel_identity import (
    IdentitySubject,
    ParcelCandidate,
    address_corrobates,
    normalize_text,
    pams_pin,
    score_candidate,
)


def test_pams_pin_normalizes_components():
    assert pams_pin("1325", "00042", "0038", "") == "1325_42_38"


def test_exact_identifiers_and_address_auto_accept():
    score = score_candidate(
        IdentitySubject(
            municipality_code="1325", block="42", lot="38",
            address="3 Huntington Court", zip_code="08501",
        ),
        ParcelCandidate(
            municipality_code="1325", block="42", lot="38",
            address="3 HUNTINGTON CT", zip_code="08501",
        ),
    )
    assert score.decision == "AUTO_ACCEPT"
    assert score.total == 100
    assert score.conflicts == []


def test_conflicting_municipality_forces_review():
    score = score_candidate(
        IdentitySubject(municipality_code="1301", address="20 Church Street"),
        ParcelCandidate(
            municipality_code="1325", block="13", lot="28", address="20 CHURCH ST"
        ),
    )
    assert score.decision == "REVIEW"
    assert "municipality_conflict" in score.conflicts


def test_house_number_conflict_is_not_auto_accepted():
    score = score_candidate(
        IdentitySubject(address="705 8th Street"),
        ParcelCandidate(
            municipality_code="1301", block="18", lot="15", address="703 8TH ST"
        ),
    )
    assert score.decision == "REVIEW"
    assert "house_number_conflict" in score.conflicts


def test_suffix_normalization():
    assert normalize_text("40 Serand Avenue") == normalize_text("40 SERAND AVE")


def test_ordinal_and_decimal_identifier_normalization():
    assert normalize_text("705 4th Avenue") == normalize_text("705 FOURTH AVE")
    assert pams_pin("1337", "34.01", "7.01") == "1337_3401_701"


def test_multi_address_corroboration_ignores_order():
    assert address_corrobates(
        "6 Shore Boulevard10 Shore Boulevard 8 Shore Boulevard, Keansburg, NJ",
        "6,8,10,SHORE BLVD",
    )
    assert not address_corrobates("6 Shore Boulevard", "7 Shore Boulevard")
