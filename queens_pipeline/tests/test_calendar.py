from pathlib import Path

import pytest

from calendar_parser import Calendar, CalendarRow, parse_calendar, parse_lines
from db import connect
from ingest_calendar import ingest

SAMPLE = Path(__file__).resolve().parents[1] / "data/queens/calendars/CourtCalendar_2026-10-14.pdf"
TABLES = ["cases", "auction_events", "calendar_snapshots", "snapshot_rows", "change_log"]


@pytest.mark.skipif(not SAMPLE.exists(), reason="sample calendar PDF is not in data/queens/calendars")
def test_sample_calendar_counts():
    # The Oct 14, 2026 export (21 pages). It includes 5393/2008, a four-digit index number.
    calendar = parse_calendar(SAMPLE)
    assert calendar.court == "Queens Supreme Court"
    assert calendar.part_selected == "FORECLOSURE AUCTION PART"
    assert calendar.date_range_start == "2026-10-14"
    assert calendar.calendar_created_at == "2026-10-14T13:28"
    assert len(calendar.rows) == 193
    assert len({row.index_number for row in calendar.rows}) == 190
    assert sum(row.outcome == "Not Held" for row in calendar.rows) == 12
    assert any(row.index_number == "5393/2008" for row in calendar.rows)


def test_parse_lines_handles_wrapped_fields_outcomes_and_captions():
    calendar = parse_lines([
        "Calendar created on: October 11, 2026 at 10:53 AM",
        "Court: Queens Supreme Court",
        "Date Range: 10/11/2026 -",
        "Part Selected: FORECLOSURE AUCTION PART",
        "Friday, October 16, 2026",
        "713725/2021 - US BANK vs. TELLO, JONNI vs. OTHERS ETAL",
        "Queens Supreme Court / Part: FORECLOSURE AUCTION PART",
        "Fully Virtual: No / Court Date Type: Courtroom",
        "Court Date Purpose: Auction-Foreclosed Property / Outcome: Not Held",
        "Plaintiff Attorney: Robertson, Anschutz, Schneid,",
        "Crane & Partners, PLLC",
        "Friday, October 23, 2026",
        "5393/2008 - U.S. BANK, N.A. vs. LEON, SEGUNDO ETAL.",
        "CMS Index: 0017567/2009",
        "Court Date Purpose: Auction-Foreclosed Property",
    ])
    assert calendar.date_range_start == "2026-10-11"
    first, second = calendar.rows
    assert (first.auction_date, first.plaintiff, first.defendant) == ("2026-10-16", "US BANK", "TELLO, JONNI vs. OTHERS ETAL")
    assert (first.purpose, first.outcome) == ("Auction-Foreclosed Property", "Not Held")
    assert (first.fully_virtual, first.court_date_type) == ("No", "Courtroom")
    assert first.plaintiff_attorney == "Robertson, Anschutz, Schneid, Crane & Partners, PLLC"
    assert (second.index_number, second.auction_date, second.cms_index) == ("5393/2008", "2026-10-23", "0017567/2009")
    assert second.justice is None and second.outcome is None


def row(index_number: str, auction_date: str, outcome: str | None = None) -> CalendarRow:
    return CalendarRow(index_number=index_number, auction_date=auction_date, caption=f"BANK vs. OWNER {index_number}",
                       plaintiff="BANK", defendant=f"OWNER {index_number}", court="Queens Supreme Court",
                       part="FORECLOSURE AUCTION PART", purpose="Auction-Foreclosed Property", outcome=outcome,
                       raw_lines=[f"{index_number} - BANK vs. OWNER"])


def calendar(start: str, rows: list[CalendarRow]) -> Calendar:
    return Calendar(calendar_created_at=f"{start}T10:00", court="Queens Supreme Court", date_range_start=start,
                    part_selected="FORECLOSURE AUCTION PART", rows=rows)


def counts(connection) -> dict[str, int]:
    return {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in TABLES}


def status(connection, index_number: str, auction_date: str) -> str:
    return connection.execute("SELECT event_status FROM auction_events WHERE index_number = ? AND auction_date = ?",
                              (index_number, auction_date)).fetchone()[0]


def lifecycle(connection, index_number: str) -> str:
    return connection.execute("SELECT lifecycle FROM cases WHERE index_number = ?", (index_number,)).fetchone()[0]


def test_ingesting_the_same_file_twice_changes_nothing(tmp_path):
    connection = connect(tmp_path / "test.db")
    week = calendar("2026-10-11", [row("1/2020", "2026-10-16"), row("2/2020", "2026-10-23", "Not Held")])
    first = ingest(connection, week, "a.pdf", "sha-1", tmp_path)
    assert first.counts["new_case"] == 2
    before = counts(connection)
    second = ingest(connection, week, "a.pdf", "sha-1", tmp_path)
    assert second.skipped and counts(connection) == before


def test_weekly_delta_covers_every_branch_and_never_deletes(tmp_path):
    connection = connect(tmp_path / "test.db")
    week1 = [row("1/2020", "2026-10-16"), row("2/2020", "2026-10-16"), row("3/2020", "2026-10-30"),
             row("4/2020", "2026-10-23"), row("5/2020", "2026-10-30"), row("6/2020", "2026-11-06")]
    first = ingest(connection, calendar("2026-10-11", week1), "w1.pdf", "sha-w1", tmp_path)
    assert first.counts["new_case"] == 6
    assert connection.execute("SELECT SUM(times_scheduled) FROM cases").fetchone()[0] == 6

    # Week 2 (range starts Oct 18): cases 1, 2 and 3 are gone, 4 moves to a new date,
    # 7 and 8 are new, 5 and 6 are unchanged.
    week2 = [row("4/2020", "2026-11-13"), row("5/2020", "2026-10-30"), row("6/2020", "2026-11-06"),
             row("7/2020", "2026-11-20"), row("8/2020", "2026-11-20")]
    keys_before = {tuple(r) for r in connection.execute("SELECT index_number, auction_date FROM auction_events")}
    second = ingest(connection, calendar("2026-10-18", week2), "w2.pdf", "sha-w2", tmp_path)
    assert second.counts == {"new_case": 2, "returning_case": 0, "new_auction_date": 1, "outcome_changed": 0,
                             "dropped_before_date": 2, "passed": 2}
    # 1 and 2 were dated Oct 16, before the range: passed. 3 (Oct 30) and 4's old Oct 23 date: dropped.
    assert [status(connection, "1/2020", "2026-10-16"), status(connection, "2/2020", "2026-10-16")] == ["passed"] * 2
    assert [status(connection, "3/2020", "2026-10-30"), status(connection, "4/2020", "2026-10-23")] == ["dropped"] * 2
    assert status(connection, "4/2020", "2026-11-13") == "scheduled"
    assert [lifecycle(connection, n) for n in ("1/2020", "2/2020", "3/2020", "4/2020")] == ["inactive"] * 3 + ["active"]
    assert connection.execute("SELECT times_scheduled FROM cases WHERE index_number = '4/2020'").fetchone()[0] == 2
    keys_after = {tuple(r) for r in connection.execute("SELECT index_number, auction_date FROM auction_events")}
    assert keys_before <= keys_after

    # Week 3: inactive case 1 comes back with a new date; 5's auction shows an outcome.
    week3 = [row("1/2020", "2026-12-04"), row("4/2020", "2026-11-13"), row("5/2020", "2026-10-30", "Not Held"),
             row("6/2020", "2026-11-06"), row("7/2020", "2026-11-20"), row("8/2020", "2026-11-20")]
    before = counts(connection)
    third = ingest(connection, calendar("2026-10-25", week3), "w3.pdf", "sha-w3", tmp_path)
    assert third.counts == {"new_case": 0, "returning_case": 1, "new_auction_date": 1, "outcome_changed": 1,
                            "dropped_before_date": 0, "passed": 0}
    assert lifecycle(connection, "1/2020") == "active"
    assert status(connection, "5/2020", "2026-10-30") == "not_held"
    after = counts(connection)
    assert all(after[table] >= before[table] for table in TABLES)
    assert after["cases"] == 8 and after["calendar_snapshots"] == 3
