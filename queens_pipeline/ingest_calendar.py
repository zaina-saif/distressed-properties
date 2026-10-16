"""Ingest one weekly WebCivil calendar PDF and record what changed since the last one.

    python ingest_calendar.py data/queens/calendars/CourtCalendar_2026-10-14.pdf

Runs in one transaction. Ingesting the same file twice is a no-op (matched by SHA-256).
Cases and events are never deleted: a case drops to 'inactive', an event to 'passed'
(its date came and went without it on the calendar) or 'dropped' (it left the calendar
before its date, which usually means it was cancelled or adjourned).

Writes data/reports/<county>_<calendar date>_delta.md and .csv, and
data/reports/<county>_drilldown_todo.csv (active cases still needing their case files).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from calendar_parser import Calendar, CalendarRow, parse_calendar
from db import DATA, connect, county_of

REPORTS = DATA / "reports"
# Report sections in order: (change_type, heading).
SECTIONS = [
    ("new_case", "New cases (need drill-down)"),
    ("returning_case", "Returning cases"),
    ("new_auction_date", "New auction dates for known cases"),
    ("outcome_changed", "Outcome changes"),
    ("dropped_before_date", "Dropped before date"),
    ("passed", "Passed"),
]
CALENDAR_FIELDS = ("cms_index", "plaintiff_attorney", "defendant_attorney", "justice")


@dataclass
class Result:
    snapshot_id: int | None
    county: str
    calendar_date: str | None
    skipped: bool = False
    counts: dict[str, int] = field(default_factory=dict)
    reports: list[Path] = field(default_factory=list)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _merge_case_rows(rows: list[CalendarRow]) -> dict:
    """One case's calendar fields; a later row's value fills a blank from an earlier one."""
    merged: dict = {"caption": None, "plaintiff": None, "defendant": None, **{name: None for name in CALENDAR_FIELDS}}
    for row in rows:
        for name in merged:
            merged[name] = merged[name] or getattr(row, name)
    return merged


def ingest(connection: sqlite3.Connection, calendar: Calendar, source_file: str, file_sha256: str,
           reports_dir: Path | None = REPORTS) -> Result:
    county = county_of(calendar.court)
    calendar_date = (calendar.calendar_created_at or "")[:10] or calendar.date_range_start
    if connection.execute("SELECT 1 FROM calendar_snapshots WHERE file_sha256 = ?", (file_sha256,)).fetchone():
        return Result(snapshot_id=None, county=county, calendar_date=calendar_date, skipped=True)
    if not calendar.date_range_start:
        raise ValueError("The calendar has no 'Date Range' start date.")
    range_start = calendar.date_range_start
    stamp = now()
    log: list[tuple] = []

    connection.execute("BEGIN")
    try:
        snapshot = connection.execute(
            """INSERT INTO calendar_snapshots (county, court, part_selected, calendar_created_at, date_range_start,
                   source_file, file_sha256, row_count, ingested_at) VALUES (?,?,?,?,?,?,?,?,?)""",
            (county, calendar.court, calendar.part_selected, calendar.calendar_created_at, range_start,
             source_file, file_sha256, len(calendar.rows), stamp)).lastrowid

        def change(index_number: str, change_type: str, detail: str | None = None) -> None:
            log.append((snapshot, county, index_number, change_type, detail, stamp))

        connection.executemany(
            "INSERT INTO snapshot_rows (snapshot_id, county, index_number, auction_date, raw_text) VALUES (?,?,?,?,?)",
            [(snapshot, county, row.index_number, row.auction_date, row.raw_text) for row in calendar.rows])

        # Cases.
        by_case: dict[str, list[CalendarRow]] = defaultdict(list)
        for row in calendar.rows:
            by_case[row.index_number].append(row)
        for index_number, rows in by_case.items():
            values = _merge_case_rows(rows)
            existing = connection.execute("SELECT lifecycle FROM cases WHERE county = ? AND index_number = ?",
                                          (county, index_number)).fetchone()
            if existing is None:
                connection.execute(
                    """INSERT INTO cases (county, index_number, caption, plaintiff, defendant, cms_index,
                           plaintiff_attorney, defendant_attorney, justice, lifecycle, first_seen_snapshot,
                           last_seen_snapshot, drilldown_status)
                       VALUES (?,?,?,?,?,?,?,?,?,'active',?,?,'needed')""",
                    (county, index_number, values["caption"], values["plaintiff"], values["defendant"],
                     values["cms_index"], values["plaintiff_attorney"], values["defendant_attorney"],
                     values["justice"], snapshot, snapshot))
                change(index_number, "new_case", values["caption"])
                continue
            if existing["lifecycle"] == "inactive":
                change(index_number, "returning_case", values["caption"])
            # Calendar fields change only to a known value; the caption fills only a blank.
            connection.execute(
                f"""UPDATE cases SET lifecycle = 'active', last_seen_snapshot = ?,
                       {", ".join(f"{name} = COALESCE(?, {name})" for name in CALENDAR_FIELDS)},
                       caption = COALESCE(caption, ?), plaintiff = COALESCE(plaintiff, ?),
                       defendant = COALESCE(defendant, ?)
                   WHERE county = ? AND index_number = ?""",
                (snapshot, *(values[name] for name in CALENDAR_FIELDS), values["caption"], values["plaintiff"],
                 values["defendant"], county, index_number))

        # Auction events.
        seen_events: set[tuple[str, str]] = set()
        for row in calendar.rows:
            key = (row.index_number, row.auction_date)
            if key in seen_events:
                continue
            seen_events.add(key)
            status = "not_held" if row.outcome else "scheduled"
            existing = connection.execute(
                """SELECT outcome, event_status FROM auction_events
                   WHERE county = ? AND index_number = ? AND auction_date = ?""", (county, *key)).fetchone()
            if existing is None:
                connection.execute(
                    """INSERT INTO auction_events (county, index_number, auction_date, court, part, court_date_type,
                           fully_virtual, purpose, outcome, event_status, first_seen_snapshot, last_seen_snapshot,
                           time, remarks)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (county, *key, row.court, row.part, row.court_date_type, row.fully_virtual, row.purpose,
                     row.outcome, status, snapshot, snapshot, row.time, row.remarks))
                connection.execute("""UPDATE cases SET times_scheduled = times_scheduled + 1
                                      WHERE county = ? AND index_number = ?""", (county, row.index_number))
                change(row.index_number, "new_auction_date", row.auction_date)
                continue
            connection.execute(
                """UPDATE auction_events SET last_seen_snapshot = ?, outcome = ?, event_status = ?,
                       time = COALESCE(?, time), remarks = COALESCE(?, remarks)
                   WHERE county = ? AND index_number = ? AND auction_date = ?""",
                (snapshot, row.outcome, status, row.time, row.remarks, county, *key))
            if existing["outcome"] != row.outcome:
                change(row.index_number, "outcome_changed",
                       f"{row.auction_date}: {existing['outcome'] or 'none'} -> {row.outcome or 'none'}")
            elif existing["event_status"] in ("passed", "dropped"):
                change(row.index_number, "new_auction_date", f"{row.auction_date} (back on the calendar)")

        # Scheduled events missing from this calendar.
        missing = connection.execute(
            """SELECT index_number, auction_date FROM auction_events
               WHERE county = ? AND event_status = 'scheduled' AND last_seen_snapshot <> ?""",
            (county, snapshot)).fetchall()
        for event in missing:
            passed = event["auction_date"] < range_start
            connection.execute(
                """UPDATE auction_events SET event_status = ?
                   WHERE county = ? AND index_number = ? AND auction_date = ?""",
                ("passed" if passed else "dropped", county, event["index_number"], event["auction_date"]))
            change(event["index_number"], "passed" if passed else "dropped_before_date", event["auction_date"])

        # A case off this calendar with nothing left scheduled goes inactive. A case still on
        # the calendar stays active even when its only entry shows an outcome ("Not Held").
        connection.execute(
            """UPDATE cases SET lifecycle = 'inactive'
               WHERE county = ? AND lifecycle = 'active' AND last_seen_snapshot <> ?
                 AND NOT EXISTS (SELECT 1 FROM auction_events e WHERE e.county = cases.county
                                 AND e.index_number = cases.index_number AND e.event_status = 'scheduled')""",
            (county, snapshot))
        connection.executemany(
            """INSERT INTO change_log (snapshot_id, county, index_number, change_type, detail, logged_at)
               VALUES (?,?,?,?,?,?)""", log)
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise

    result = Result(snapshot_id=snapshot, county=county, calendar_date=calendar_date)
    new_cases = {entry[2] for entry in log if entry[3] == "new_case"}
    for change_type, _ in SECTIONS:
        result.counts[change_type] = sum(1 for entry in log if entry[3] == change_type
                                         and not (change_type == "new_auction_date" and entry[2] in new_cases))
    if reports_dir is not None:
        result.reports = write_reports(connection, result, log, reports_dir)
    return result


def _captions(connection: sqlite3.Connection, county: str) -> dict[str, str]:
    return {row["index_number"]: row["caption"] for row in
            connection.execute("SELECT index_number, caption FROM cases WHERE county = ?", (county,))}


def write_reports(connection: sqlite3.Connection, result: Result, log: list[tuple], reports_dir: Path) -> list[Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    county = result.county
    prefix = county.lower().replace(" ", "_")
    captions = _captions(connection, county)
    new_cases = {entry[2] for entry in log if entry[3] == "new_case"}
    rows_by_section: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for _, _, index_number, change_type, detail, _ in log:
        if change_type == "new_auction_date" and index_number in new_cases:
            continue  # a new case's dates are part of its "new case" entry
        rows_by_section[change_type].append((index_number, detail or ""))
    next_dates = next_auction_dates(connection, county)

    markdown = [f"# {county} calendar delta: {result.calendar_date}", "",
                f"Snapshot {result.snapshot_id}.", ""]
    markdown += [f"- {heading}: **{result.counts[change_type]}**" for change_type, heading in SECTIONS]
    with_csv: list[dict] = []
    for change_type, heading in SECTIONS:
        entries = sorted(rows_by_section.get(change_type, []))
        markdown += ["", f"## {heading} ({len(entries)})", ""]
        if not entries:
            markdown.append("None.")
            continue
        markdown += ["| Index number | Caption | Detail |", "|---|---|---|"]
        for index_number, detail in entries:
            if change_type == "new_case":
                detail = f"next auction {next_dates.get(index_number) or 'none scheduled'}"
            caption = (captions.get(index_number) or "").replace("|", "/")
            markdown.append(f"| {index_number} | {caption} | {detail} |")
            with_csv.append({"section": heading, "index_number": index_number,
                             "caption": captions.get(index_number) or "", "detail": detail})
    md_path = reports_dir / f"{prefix}_{result.calendar_date}_delta.md"
    md_path.write_text("\n".join(markdown) + "\n")
    csv_path = md_path.with_suffix(".csv")
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["section", "index_number", "caption", "detail"])
        writer.writeheader()
        writer.writerows(with_csv)
    return [md_path, csv_path, write_drilldown_todo(connection, county, reports_dir)]


def next_auction_dates(connection: sqlite3.Connection, county: str) -> dict[str, str]:
    return {row["index_number"]: row["next_date"] for row in connection.execute(
        """SELECT index_number, MIN(auction_date) AS next_date FROM auction_events
           WHERE county = ? AND event_status = 'scheduled' GROUP BY index_number""", (county,))}


def case_file_name(index_number: str) -> str:
    """'713725/2021' -> '713725-2021.pdf'."""
    return f"{index_number.replace('/', '-')}.pdf"


def write_drilldown_todo(connection: sqlite3.Connection, county: str, reports_dir: Path) -> Path:
    next_dates = next_auction_dates(connection, county)
    cases = connection.execute(
        """SELECT index_number, caption FROM cases
           WHERE county = ? AND lifecycle = 'active' AND drilldown_status = 'needed'""", (county,)).fetchall()
    rows = sorted(cases, key=lambda case: (next_dates.get(case["index_number"]) or "9999", case["index_number"]))
    path = reports_dir / f"{county.lower().replace(' ', '_')}_drilldown_todo.csv"
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["index_number", "caption", "next_auction_date", "save_as"])
        for case in rows:
            writer.writerow([case["index_number"], case["caption"], next_dates.get(case["index_number"]) or "",
                             case_file_name(case["index_number"])])
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pdf", type=Path)
    args = parser.parse_args()
    calendar = parse_calendar(args.pdf)
    result = ingest(connect(), calendar, str(args.pdf), sha256_file(args.pdf))
    if result.skipped:
        print(f"{args.pdf.name} was already ingested; nothing changed.")
        return
    print(f"Snapshot {result.snapshot_id}: {len(calendar.rows)} rows, "
          f"{len({row.index_number for row in calendar.rows})} cases ({result.county}, {result.calendar_date})")
    for change_type, heading in SECTIONS:
        print(f"  {heading}: {result.counts[change_type]}")
    for path in result.reports:
        print(f"  wrote {path}")


if __name__ == "__main__":
    main()
