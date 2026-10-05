from bs4 import BeautifulSoup

from pipeline.adapters.monmouth import MonmouthCivilViewAdapter


def test_extract_status_history_preserves_repeated_events() -> None:
    soup = BeautifulSoup(
        """
        <table id="longTable">
          <tr><th>Status</th><th>Date</th></tr>
          <tr><td>Scheduled</td><td>8/31/2026</td></tr>
          <tr><td>Bankrupt</td><td>5/26/2026</td></tr>
          <tr><td>Adjournment Defendant</td><td>2/2/2026</td></tr>
          <tr><td>Adjournment Defendant</td><td>1/5/2026</td></tr>
        </table>
        """,
        "html.parser",
    )

    history = MonmouthCivilViewAdapter()._extract_status_history(soup)

    assert [event["status"] for event in history] == [
        "scheduled", "bankruptcy", "adjourned", "adjourned"
    ]
    assert history[2]["raw_status"] == "Adjournment Defendant"
    assert history[2]["sale_date"] == "2026-02-02T00:00:00"


def test_status_date_header_is_used_as_sale_date_for_morris() -> None:
    from pipeline.adapters.civilview_county import CountyCivilViewAdapter

    soup = BeautifulSoup(
        """
        <table><tr><td>Morris County, NJ - updated 10/4/2026</td></tr></table>
        <table>
          <tr><th></th><th>Sheriff #</th><th>Status Date</th><th>Plaintiff</th><th>Defendant</th><th>Address</th></tr>
          <tr><td>View Details</td><td>23001440</td><td>10/15/2026</td><td>Bank</td><td>Owner</td><td>6 Trout Brook Court Chester NJ</td></tr>
        </table>
        """,
        "html.parser",
    )
    adapter = CountyCivilViewAdapter("Morris", 9)

    table = adapter._find_sales_table(soup)
    record = adapter._parse_row(table.find_all("tr")[1], adapter._get_header_map(table))

    assert record.sheriff_number == "23001440"
    assert record.sale_date.isoformat() == "2026-10-15T00:00:00"
    assert record.address == "6 Trout Brook Court Chester NJ"


def test_sales_date_header_wins_over_status_date() -> None:
    soup = BeautifulSoup(
        "<table><tr><th>Sheriff #</th><th>Status Date</th><th>Sales Date</th>"
        "<th>Plaintiff</th><th>Defendant</th><th>Address</th></tr></table>",
        "html.parser",
    )
    adapter = MonmouthCivilViewAdapter()

    assert adapter._get_header_map(soup.find("table"))["sale_date"] == 2


def test_parse_date_accepts_time_without_seconds() -> None:
    parsed = MonmouthCivilViewAdapter._parse_date("10/19/2026 02:00 PM")

    assert parsed.isoformat() == "2026-10-19T14:00:00"


def test_detail_page_error_redirect_is_not_parsed_as_description() -> None:
    import asyncio

    import httpx

    from pipeline.adapters.base import RawSheriffSale

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/Sales/SaleDetails":
            return httpx.Response(
                302,
                headers={"Location": "/Home/Index?aspxerrorpath=/Sales/SaleDetails"},
            )
        return httpx.Response(200, text="<title>Sales Web | Tyler Technologies</title>Allen County, OH")

    record = RawSheriffSale(
        county="Atlantic", sheriff_number="F-1", address="1 Main St", sale_date=None,
        status="scheduled", upset_price=None,
        source_url="https://salesweb.civilview.com/Sales/SaleDetails?PropertyId=1",
        raw_payload={},
    )

    async def run() -> RawSheriffSale:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
            return await MonmouthCivilViewAdapter().enrich_record_from_detail_page(client, record)

    enriched = asyncio.run(run())

    assert "aspxerrorpath" in enriched.raw_payload["detail_page_redirected_to"]
    assert "description_text" not in enriched.raw_payload
    assert "status_history" not in enriched.raw_payload
