from decimal import Decimal

from pipeline.import_nyc_acris_sales import LEGAL_FIELDS, MASTER_FIELDS, parse


def test_acris_mapping_and_privacy() -> None:
    parsed = parse({"document_id": "2025010200012001", "doc_type": "DEED",
                    "document_date": "2025-01-01T00:00:00.000", "document_amt": "850000",
                    "recorded_datetime": "2025-01-02T00:00:00.000"},
                   {"borough": "3", "block": "2488", "lot": "1504", "property_type": "F1",
                    "street_number": "1110", "street_name": "MANHATTAN AVENUE"})
    assert parsed is not None
    sale, snapshot = parsed
    assert sale[2:7] == ("Kings", "NYC:BBL:3024881504", "2025010200012001", sale[5], Decimal("850000"))
    assert snapshot[5:8] == ("1110 MANHATTAN AVENUE", "F1", "F1")
    assert not any(any(term in field for term in ("party_name", "owner", "mailing"))
                   for field in MASTER_FIELDS + LEGAL_FIELDS)
