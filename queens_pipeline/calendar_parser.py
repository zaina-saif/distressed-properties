"""Parse a WebCivil Supreme "Justice/Part Calendar Details" PDF export.

The export lists one entry per scheduled court date, grouped under date lines:

    Friday, October 16, 2026
    713725/2021 - US BANK NATIONAL ASSOCIATION vs. TELLO, JONNI R. ETAL
    Queens Supreme Court / Part: FORECLOSURE AUCTION PART
    CMS Index: 0017567/2009
    Justice: (Master Foreclosure Part), MFJ
    Fully Virtual: No / Court Date Type: Courtroom
    Court Date Purpose: Auction-Foreclosed Property / Outcome: Not Held
    Plaintiff Attorney: DRUCKMAN LAW GROUP PLLC
    Defendant Attorney: ...

Field lines come in varying order and long values wrap onto the next line
("Plaintiff Attorney: Robertson, Anschutz, Schneid," / "Crane & Partners, PLLC").
Every page starts with the report title and the last one ends with "Page N of M".

The "Court Calendar Details" export (a court's whole part, printed from the browser, as
New York County's) differs: "Court Part Selected:" and "Date Selected:" head it, date
lines have no comma ("Tuesday October 20, 2026"), entries add "Time:", "Remarks:"
(continued on the next line: "CANCELED VIA EMAIL 9/18/26"), "Calendar Number:" and
"Year Filed:", and every page carries the browser's header and the page's URL.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pdfplumber

TITLES = {"WebCivil Supreme - Justice/Part Calendar Details", "WebCivil Supreme - Court Calendar Details"}
# "Page 2 of 3"; a browser print's header ("10/16/26, 2:33 PM WebCivil Supreme") and footer (the URL, "1/9").
PAGE_FOOTER = re.compile(r"^Page \d+ of \d+$|^\d{1,2}/\d{1,2}/\d{2}, \d{1,2}:\d{2} [AP]M WebCivil Supreme$|^https?://\S+.* \d+/\d+$")
DATE_LINE = re.compile(r"^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),? "
                       r"([A-Z][a-z]+ \d{1,2}, \d{4})$")
# Older cases have shorter index numbers ("5393/2008").
ENTRY = re.compile(r"^(\d{3,6}/\d{4}) - (.*)$")
# Label -> field. "Queens Supreme Court / Part: ..." is matched separately (the court name varies).
LABELS = {
    "CMS Index": "cms_index",
    "Justice": "justice",
    "Fully Virtual": "fully_virtual",
    "Court Date Purpose": "purpose",
    "Plaintiff Attorney": "plaintiff_attorney",
    "Defendant Attorney": "defendant_attorney",
    "Time": "time",
    "Remarks": "remarks",
    "Calendar Number": "calendar_number",
    "Year Filed": "year_filed",
}
LABEL_LINE = re.compile(r"^(" + "|".join(map(re.escape, LABELS)) + r"):\s*(.*)$")
COURT_LINE = re.compile(r"^(.+? Court) / Part:\s*(.*)$")


@dataclass
class CalendarRow:
    index_number: str
    auction_date: str  # ISO date
    caption: str
    plaintiff: str | None = None
    defendant: str | None = None
    court: str | None = None
    part: str | None = None
    cms_index: str | None = None
    justice: str | None = None
    fully_virtual: str | None = None
    court_date_type: str | None = None
    purpose: str | None = None
    outcome: str | None = None
    plaintiff_attorney: str | None = None
    defendant_attorney: str | None = None
    time: str | None = None
    remarks: str | None = None
    calendar_number: str | None = None
    year_filed: str | None = None
    raw_lines: list[str] = field(default_factory=list)

    @property
    def raw_text(self) -> str:
        return "\n".join(self.raw_lines)


@dataclass
class Calendar:
    calendar_created_at: str | None  # ISO datetime
    court: str | None
    date_range_start: str | None  # ISO date
    part_selected: str | None
    rows: list[CalendarRow]


def pdf_lines(path: Path) -> list[str]:
    """Every page's lines with the per-page title and page footer removed, joined into one stream."""
    lines: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for line in (page.extract_text() or "").splitlines():
                line = " ".join(line.split())
                if line and line not in TITLES and not PAGE_FOOTER.match(line):
                    lines.append(line)
    return lines


def _iso_date(value: str, fmt: str) -> str:
    return datetime.strptime(value, fmt).date().isoformat()


def parse_lines(lines: list[str]) -> Calendar:
    header = {"calendar_created_at": None, "court": None, "date_range_start": None, "part_selected": None}
    rows: list[CalendarRow] = []
    current_date: str | None = None
    row: CalendarRow | None = None
    last_field: str | None = None
    for line in lines:
        if not rows and row is None:
            # Report header, before the first entry.
            if match := re.match(r"^Calendar created on:\s*(.+? \d{4}) at (\d{1,2}:\d{2} [AP]M)$", line):
                header["calendar_created_at"] = datetime.strptime(
                    f"{match[1]} {match[2]}", "%B %d, %Y %I:%M %p").isoformat(timespec="minutes")
                continue
            if match := re.match(r"^Court:\s*(.+)$", line):
                header["court"] = match[1]
                continue
            if match := re.match(r"^Date Range:\s*(\d{1,2}/\d{1,2}/\d{4})", line):
                header["date_range_start"] = _iso_date(match[1], "%m/%d/%Y")
                continue
            if match := re.match(r"^Date Selected:\s*(\d{1,2}/\d{1,2}/\d{4})", line):
                header["date_range_start"] = _iso_date(match[1], "%m/%d/%Y")
                continue
            if match := re.match(r"^(?:Court )?Part Selected:\s*(.+)$", line):
                header["part_selected"] = match[1]
                continue
        if match := DATE_LINE.match(line):
            current_date = _iso_date(match[1], "%B %d, %Y")
            last_field = None
            continue
        if match := ENTRY.match(line):
            if current_date is None:
                raise ValueError(f"Entry before any date line: {line}")
            row = CalendarRow(index_number=match[1], auction_date=current_date, caption=match[2])
            row.raw_lines.append(line)
            rows.append(row)
            last_field = "caption"
            continue
        if row is None:
            continue
        row.raw_lines.append(line)
        if match := COURT_LINE.match(line):
            row.court, row.part = match[1], match[2] or None
            last_field = "part"
        elif match := LABEL_LINE.match(line):
            last_field = LABELS[match[1]]
            setattr(row, last_field, match[2] or None)
        elif last_field:
            # A wrapped value continues the previous field.
            previous = getattr(row, last_field)
            setattr(row, last_field, f"{previous} {line}" if previous else line)
    for row in rows:
        _finish(row)
    return Calendar(rows=rows, **header)


def _finish(row: CalendarRow) -> None:
    # Split on the first " vs. " only: names can contain "vs." themselves.
    plaintiff, sep, defendant = row.caption.partition(" vs. ")
    row.plaintiff, row.defendant = (plaintiff.strip() or None, defendant.strip() or None) if sep else (row.caption, None)
    if row.purpose and (match := re.match(r"^(.*?)\s*/\s*Outcome:\s*(.*)$", row.purpose)):
        row.purpose, row.outcome = match[1] or None, match[2] or None
    if row.fully_virtual and (match := re.match(r"^(.*?)\s*/\s*Court Date Type:\s*(.*)$", row.fully_virtual)):
        row.fully_virtual, row.court_date_type = match[1] or None, match[2] or None


def parse_calendar(path: Path) -> Calendar:
    return parse_lines(pdf_lines(path))
