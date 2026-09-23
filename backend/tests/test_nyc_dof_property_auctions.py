import json
from datetime import date
from pathlib import Path

import pytest

from pipeline.load_nyc_dof_property_auctions import validate


DATA = Path(__file__).resolve().parents[1] / "data/sheriff_sales/nyc_dof_property_auctions.json"


def test_official_pdf_snapshot_is_historical_and_not_sold() -> None:
    records = json.loads(DATA.read_text())
    validate(records, date(2026, 9, 16))
    assert len(records) == 1
    assert records[0]["bbl"] == "1015391277"
    assert records[0]["sale_date"] == "2021-09-08"
    assert records[0]["judgment_amount"] is None
    assert records[0]["sale_result"] is None
    assert records[0]["is_active"] is False


def test_past_notice_cannot_be_active_or_claim_sold() -> None:
    record = json.loads(DATA.read_text())[0]
    record["is_active"] = True
    with pytest.raises(ValueError, match="Past notice"):
        validate([record], date(2026, 9, 16))
    record["is_active"] = False
    record["current_status"] = "sold"
    with pytest.raises(ValueError):
        validate([record], date(2026, 9, 16))
