import json

import pytest
from pypdf import PdfWriter

from pipeline.load_nyc_kings_local_notices import DETAILS_INPUT, validate


def write_notice_pdfs(records: list[dict], pdf_dir) -> None:
    pdf_dir.mkdir()
    for record in records:
        writer = PdfWriter()
        writer.add_blank_page(width=72, height=72)
        with (pdf_dir / record["filename"]).open("wb") as handle:
            writer.write(handle)


def test_eight_local_notices_have_verified_case_and_parcel_identity(tmp_path) -> None:
    records = json.loads(DETAILS_INPUT.read_text())
    pdf_dir = tmp_path / "notices"
    write_notice_pdfs(records, pdf_dir)
    validate(records, pdf_dir)
    assert len(records) == 8
    assert len({r["bbl"] for r in records}) == 8
    assert all(r["sale_result"] is None for r in records)
    assert next(r for r in records if r["filename"] == "1025 E 13 STREET.pdf")["judgment_amount"] is None
    assert next(r for r in records if r["filename"] == "1070 E 73 STREET UNIT 98.pdf")["notice_completeness"] == "page 1 of 2 only"


def test_lien_amount_cannot_be_mislabeled_as_judgment(tmp_path) -> None:
    record = json.loads(DETAILS_INPUT.read_text())[0]
    record["judgment_amount"] = record["lien_amount"]
    pdf_dir = tmp_path / "notices"
    write_notice_pdfs([record], pdf_dir)
    with pytest.raises(ValueError, match="conflated"):
        validate([record], pdf_dir)
