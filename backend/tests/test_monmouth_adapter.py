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
