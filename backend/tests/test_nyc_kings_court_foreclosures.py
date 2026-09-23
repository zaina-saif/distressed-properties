import json
from datetime import date
from pathlib import Path

import pytest

from pipeline.load_nyc_kings_court_foreclosures import parse_snapshot


DATA = Path(__file__).resolve().parents[1] / "data/sheriff_sales/nyc_kings_court_foreclosure_index.json"


def test_court_index_yields_address_only_referee_auctions() -> None:
    records = parse_snapshot(json.loads(DATA.read_text()), date(2026, 9, 17))
    assert len(records) == 27
    assert len({record["sheriff_number"] for record in records}) == 27
    assert all(record["sale_type"] == "Court foreclosure auction" for record in records)
    assert all(record["sale_date"] == "2026-09-17" for record in records)
    assert all(record["bbl"] is None and record["sale_result"] is None for record in records)
    assert records[0]["address"] == "1025 E 13 STREET, Brooklyn, NY"
    assert records[0]["source_url"].endswith("1025%20E%2013%20STREET.pdf")


def test_snapshot_rejects_invalid_or_duplicate_links() -> None:
    snapshot = json.loads(DATA.read_text())
    snapshot["notice_filenames"].append(snapshot["notice_filenames"][0])
    with pytest.raises(ValueError, match="Duplicate"):
        parse_snapshot(snapshot, date(2026, 9, 17))
    snapshot["notice_filenames"][-1] = "../unofficial.pdf"
    with pytest.raises(ValueError, match="Invalid"):
        parse_snapshot(snapshot, date(2026, 9, 17))
