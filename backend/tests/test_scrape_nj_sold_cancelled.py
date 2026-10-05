from pipeline.adapters.base import RawSheriffSale
from pipeline.scrape_nj_sold_cancelled import _classify


def _record(history):
    return RawSheriffSale(
        county="Union", sheriff_number="CH-1", address="1 Main St", sale_date=None,
        status="scheduled", upset_price=None, source_url=None,
        raw_payload={"status_history": history},
    )


def test_purchase_event_is_sold():
    assert _classify(_record([{"raw_status": "Purchased - 3rd Party"}])).status == "sold"


def test_history_without_sale_is_cancelled():
    assert _classify(_record([{"raw_status": "Cancelled"}])).status == "cancelled"


def test_missing_history_is_unverified_not_cancelled():
    record = _classify(_record([]))

    assert record.status == "sold_or_cancelled_unverified"
    assert record.raw_payload["historical_search_status"] == "sold_or_cancelled_unverified"
