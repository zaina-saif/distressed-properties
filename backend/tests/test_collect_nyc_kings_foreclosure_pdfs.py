from datetime import date

import httpx
import pytest

from pipeline.collect_nyc_kings_foreclosure_pdfs import (
    CourtAccessBlocked, checked_get, parse_calendar_date, parse_notice, parse_pdf_links,
)


def test_parse_court_calendar_and_pdf_links() -> None:
    page = "<main>The next scheduled auction date will be September 17, 2026.</main>"
    directory = "https://www.nycourts.gov/legacyPDFs/courts/2jd/kings/civil/foreclosures/foreclosure%20scans/"
    listing = '<a href="1025%20E%2013%20STREET.pdf">1025 E 13 STREET.pdf</a>'
    assert parse_calendar_date(page) == date(2026, 9, 17).isoformat()
    assert parse_pdf_links(listing, directory) == [{
        "filename": "1025 E 13 STREET.pdf",
        "source_url": directory + "1025%20E%2013%20STREET.pdf",
    }]


def test_parse_notice_only_when_identifiers_are_unambiguous() -> None:
    notice = ("Index No. 512345/2024\nBlock: 1234\nLot: 56\n"
              "Plaintiff: Bank A\nDefendant: Person B\n"
              "I will sell at public auction at Room 224 on September 17, 2026 at 2:30 PM.\n"
              "Approximate amount of judgment is $1,375,785.47 plus interest.")
    fields = parse_notice(notice)
    assert fields["court_case_number"] == "512345/2024"
    assert fields["bbl"] == "3012340056"
    assert fields["plaintiff"] == "Bank A"
    assert fields["defendant"] == "Person B"
    assert fields["notice_sale_date"] == "2026-09-17"
    assert fields["judgment_amount"] == "1375785.47"
    assert parse_notice(notice + "\nBlock: 9999")["bbl"] is None


def test_cloudflare_response_is_reported_as_blocked() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(
        403, text="<html><title>Just a moment...</title></html>",
        headers={"content-type": "text/html"}, request=request))
    with httpx.Client(transport=transport) as client:
        with pytest.raises(CourtAccessBlocked, match="access challenge"):
            checked_get(client, "https://www.nycourts.gov/notice.pdf")


def test_directory_rejects_offsite_pdf() -> None:
    directory = "https://www.nycourts.gov/legacyPDFs/courts/2jd/kings/civil/foreclosures/foreclosure%20scans/"
    with pytest.raises(ValueError, match="leaves court directory"):
        parse_pdf_links('<a href="https://example.org/fake.pdf">fake</a>', directory)
