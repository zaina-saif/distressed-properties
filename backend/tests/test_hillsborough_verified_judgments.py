import pytest

from pipeline.load_hillsborough_verified_judgments import validate


NOTICE = {"court_case_number": "19-CA-006420", "street_address": "1502 W BRANDON DR", "zip_code": "33603"}
JUDGMENT = {"court_case_number": "19-CA-006420", "street_address": "1502 W BRANDON DR",
            "zip_code": "33603", "judgment_amount": "263216.09",
            "judgment_amount_as_of_date": "2019-09-19",
            "source_url": "https://publicaccess.hillsclerk.com/PAVDirectSearch/index.html?CQID=350"}


def test_verified_judgment_must_match_notice_identity() -> None:
    validate([JUDGMENT], [NOTICE])
    with pytest.raises(ValueError, match="does not match"):
        validate([{**JUDGMENT, "zip_code": "33503"}], [NOTICE])


def test_verified_judgment_requires_positive_amount_and_clerk_source() -> None:
    with pytest.raises(ValueError, match="positive"):
        validate([{**JUDGMENT, "judgment_amount": "0"}], [NOTICE])
    with pytest.raises(ValueError, match="clerk source"):
        validate([{**JUDGMENT, "source_url": "https://example.com"}], [NOTICE])
