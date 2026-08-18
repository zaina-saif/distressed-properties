from decimal import Decimal

from pipeline.enrich_rentcast import subject_matches
from pipeline.providers.base import ValuationResult


def test_subject_match_accepts_standard_street_abbreviation() -> None:
    candidate = {
        "street_address": "11 Manor Drive",
        "city": "Neptune",
        "state": "NJ",
        "zip_code": "07753",
    }
    result = ValuationResult(
        provider="rentcast",
        provider_property_id="example",
        estimated_value=Decimal("641000"),
        low_value=Decimal("543000"),
        high_value=Decimal("739000"),
        formatted_address="11 Manor Dr, Neptune, NJ 07753",
        address_line_1="11 Manor Dr",
        city="Neptune",
        state="NJ",
        zip_code="07753",
        comparable_count=15,
        raw_response={},
    )

    assert subject_matches(candidate, result) is True
