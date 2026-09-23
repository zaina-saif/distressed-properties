import json

import pytest

from pipeline.load_nyc_kings_local_notices import DETAILS_INPUT, validate


def test_eight_local_notices_have_verified_case_and_parcel_identity() -> None:
    records = json.loads(DETAILS_INPUT.read_text())
    validate(records)
    assert len(records) == 8
    assert len({r["bbl"] for r in records}) == 8
    assert all(r["sale_result"] is None for r in records)
    assert next(r for r in records if r["filename"] == "1025 E 13 STREET.pdf")["judgment_amount"] is None
    assert next(r for r in records if r["filename"] == "1070 E 73 STREET UNIT 98.pdf")["notice_completeness"] == "page 1 of 2 only"


def test_lien_amount_cannot_be_mislabeled_as_judgment() -> None:
    record = json.loads(DETAILS_INPUT.read_text())[0]
    record["judgment_amount"] = record["lien_amount"]
    with pytest.raises(ValueError, match="conflated"):
        validate([record])
