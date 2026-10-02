from __future__ import annotations

import asyncio
import httpx
import pytest

from app.liens.matching import match_public_record
from app.liens.monmouth import MONMOUTH_OPRS_URL, MonmouthOPRSAdapter, parse_oprs_results
from app.liens.sources import PropertyIdentity


IDENTITY = PropertyIdentity(
    property_id="property-1",
    address="7 Max Place, Howell, NJ 07731",
    county="Monmouth",
    municipality="Howell",
    block="23705",
    lot="13",
    pams_pin="1321_23705_13",
    current_owners=("George Calderon",),
)


RESULT_HTML = """
<html><body><table id="results"><tr>
<th>Instrument Number</th><th>Document Type</th><th>Grantor</th><th>Grantee</th><th>Amount</th><th>Recorded Date</th>
</tr><tr><td>M-100</td><td>Mortgage</td><td>George Calderon</td><td>Example Bank</td><td>$400,000.00</td><td>01/02/2020</td></tr>
<tr><td>D-200</td><td>Mortgage Discharge (M-100)</td><td>George Calderon</td><td>Example Bank</td><td></td><td>02/02/2022</td></tr>
</table></body></html>
"""


def test_oprs_parser_normalizes_mortgage_and_discharge_relationship():
    raw, liens, relationships = parse_oprs_results(RESULT_HTML, MONMOUTH_OPRS_URL, IDENTITY)
    assert len(raw) == 2
    assert [item.lien_type for item in liens] == ["MORTGAGE", "MORTGAGE_DISCHARGE"]
    assert liens[0].current_amount == 400000
    assert liens[0].status.value == "POSSIBLY_ACTIVE"
    assert liens[1].status.value == "DISCHARGED"
    assert relationships == [("M-100", "D-200", "DISCHARGES", 95)]
    assert all(item.match_confidence >= 90 for item in liens)


def test_oprs_parser_deduplicates_identical_rows_and_handles_missing_fields():
    html = RESULT_HTML.replace("</tr>\n<tr><td>D-200", "</tr>\n<tr><td>M-100</td><td>Mortgage</td><td>George Calderon</td><td>Example Bank</td><td>$400,000.00</td><td>01/02/2020</td></tr>\n<tr><td>D-200")
    raw, liens, _ = parse_oprs_results(html, MONMOUTH_OPRS_URL, IDENTITY)
    assert len(raw) == 2
    assert len(liens) == 2
    assert any(item.lien_type == "MORTGAGE_DISCHARGE" for item in liens)


def test_owner_only_match_is_low_confidence_and_manual_review():
    identity = PropertyIdentity(property_id="p", address="Unknown", county="Monmouth", current_owners=("John Smith",))
    result = match_public_record(identity, {"debtor_name": "John Smith"})
    assert result.confidence == 45
    assert result.requires_manual_review is True


def test_adapter_uses_public_form_and_returns_records():
    form_html = '<form id="aspnetForm"><input type="hidden" name="__VIEWSTATE" value="x" /></form>'

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, text=form_html)
        return httpx.Response(200, text=RESULT_HTML)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
            adapter = MonmouthOPRSAdapter(client)
            return await adapter.search_property_with_raw(IDENTITY)
    liens, raw, relationships = asyncio.run(run())
    assert len(liens) == 2
    assert len(raw) == 2
    assert relationships[0][2] == "DISCHARGES"


def test_adapter_source_failure_is_not_silently_treated_as_no_records():
    async def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("source unavailable")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = MonmouthOPRSAdapter(client)
            await adapter.search_property(IDENTITY)
    with pytest.raises(httpx.ConnectError):
        asyncio.run(run())
