"""Read the per-case files saved by hand and fill in each case's drill-down details.

    python ingest_case_files.py                      # every case file in data/queens/cases/
    python ingest_case_files.py 713725/2021          # one case
    python ingest_case_files.py --cases-dir ~/Documents/.../QueensSupremeCourt
    python ingest_case_files.py --county "New York" --cases-dir <folder>   # another county's cases

Files belong to a case by name: the index number with "/" written as "-" (spaces and a
":" around it are tolerated, as in "705527- 2014 summons.pdf"), then a space, "_" or ".".
Other files are listed and skipped. Each file is split into documents and every document
is classified from its text (see case_parsers). Re-running is safe: every write is an upsert.

Field precedence: the Notice of Sale (the newest court-checked address) over the
summons and complaint, over a notice of pendency; among complaints the latest filing wins.
Every value is recorded in field_sources with its section, file and method ('regex').
drilldown_status is 'done' once the case detail, appearances and e-filed document list
are all parsed, otherwise 'partial'.
"""
from __future__ import annotations

import argparse
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

import pdfplumber

from case_parsers import (Document, index_from_file_name, parse_appearances, parse_case_detail,
                          parse_notice_of_pendency, parse_notice_of_sale, parse_summons, split_documents)
from db import DATA, connect
from ingest_calendar import REPORTS, write_drilldown_todo
from pdf_text import page_texts, sha256_file

CASES_DIR = DATA / "queens" / "cases"
COUNTY = "Queens"  # set by --county
# Lower rank wins.
SECTION_RANK = {"notice_of_sale": 0, "summons_complaint": 1, "notice_of_pendency": 2, "case_detail": 3}
CASE_FIELDS = ("property_address", "city", "zip", "borough_block_lot", "referee_name", "unpaid_principal",
               "approximate_judgment", "approximate_lien_amount",
               "original_mortgagee", "case_status", "filing_date", "initiating_doc", "initiating_doc_date", "judgment_date")
FILL_IF_BLANK = ("cms_index", "justice", "caption")


@dataclass
class Candidate:
    field: str
    value: object
    section: str
    source_file: str
    rank: tuple


@dataclass
class CaseResult:
    index_number: str
    files: dict[str, list[str]] = field(default_factory=dict)  # file -> sections
    sections: set[str] = field(default_factory=set)
    fields: dict[str, object] = field(default_factory=dict)
    appearances: int = 0
    status: str = "needed"
    on_calendar: bool = True


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag in ("br", "p", "div", "tr", "li", "h1", "h2", "h3"):
            self.parts.append("\n")


def html_pages(path: Path) -> list[str]:
    parser = _Text()
    parser.feed(path.read_text(errors="replace"))
    return ["".join(parser.parts)]


def group_files(folder: Path, only: str | None = None) -> tuple[dict[str, list[Path]], list[Path]]:
    groups: dict[str, list[Path]] = defaultdict(list)
    ignored: list[Path] = []
    for path in sorted(folder.iterdir()):
        if path.is_dir() or path.name.startswith("."):
            continue
        index_number = index_from_file_name(path.name)
        if not index_number or path.suffix.lower() not in (".pdf", ".html", ".htm"):
            ignored.append(path)
        elif only is None or index_number == only:
            groups[index_number].append(path)
    return groups, ignored


def read_case(index_number: str, paths: list[Path], ocr: bool = True) -> tuple[CaseResult, list[Candidate], list[dict]]:
    result = CaseResult(index_number=index_number)
    candidates: list[Candidate] = []
    appearances: list[dict] = []
    for path in paths:
        if path.suffix.lower() == ".pdf":
            pages, _ = page_texts(path, ocr=ocr)
        else:
            pages = html_pages(path)
        documents = split_documents(pages)
        result.files[path.name] = [document.section for document in documents]
        for document in documents:
            if document.section == "appearances" and path.suffix.lower() == ".pdf":
                with pdfplumber.open(path) as pdf:
                    rows = parse_appearances([pdf.pages[number] for number in document.pages])
                if rows:
                    appearances += rows
                    result.sections.add("appearances")
                continue
            values = _parse(document)
            if values.pop("_parsed", False):
                result.sections.add(document.section)
            rank = (SECTION_RANK.get(document.section, 9), -(document.doc_number or 0))
            for name, value in values.items():
                candidates.append(Candidate(name, value, document.section, path.name, rank))
            if document.doc_number == 1 and document.filed_date:
                title = values.get("document_title") or document.section.replace("_", " ").title()
                for name, value in (("initiating_doc", title), ("initiating_doc_date", document.filed_date),
                                    ("filing_date", document.filed_date)):
                    candidates.append(Candidate(name, value, document.section, path.name, (0, 0)))
    return result, candidates, appearances


def _parse(document: Document) -> dict:
    if document.section == "notice_of_sale":
        values = parse_notice_of_sale(document.text, COUNTY)
    elif document.section == "summons_complaint":
        values = parse_summons(document, COUNTY)
    elif document.section == "notice_of_pendency":
        values = parse_notice_of_pendency(document, COUNTY)
    elif document.section == "case_detail":
        values = {k: v for k, v in parse_case_detail(document.text).items() if v and k != "index_number"}
    else:
        return {}
    values.pop("notice_auction_date", None)
    values.pop("document_title", None) if document.doc_number != 1 else None
    return {**values, "_parsed": True}


def choose(candidates: list[Candidate]) -> dict[str, Candidate]:
    chosen: dict[str, Candidate] = {}
    for candidate in sorted(candidates, key=lambda c: c.rank):
        if candidate.field != "document_title":
            chosen.setdefault(candidate.field, candidate)
    return chosen


def save_case(connection: sqlite3.Connection, result: CaseResult, candidates: list[Candidate],
              appearances: list[dict], file_hashes: dict[str, str], methods: dict[str, str]) -> None:
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    chosen = choose(candidates)
    connection.execute("BEGIN")
    try:
        exists = connection.execute("SELECT 1 FROM cases WHERE county = ? AND index_number = ?",
                                    (COUNTY, result.index_number)).fetchone()
        if not exists:
            # Files for a case that is on no ingested calendar: kept, but inactive.
            result.on_calendar = False
            connection.execute("""INSERT INTO cases (county, index_number, lifecycle, drilldown_status)
                                  VALUES (?, ?, 'inactive', 'needed')""", (COUNTY, result.index_number))
        for name, candidate in chosen.items():
            column = name if name in CASE_FIELDS or name in FILL_IF_BLANK else None
            if column is None:
                continue
            if column in FILL_IF_BLANK:
                connection.execute(f"UPDATE cases SET {column} = COALESCE({column}, ?) WHERE county = ? AND index_number = ?",
                                   (candidate.value, COUNTY, result.index_number))
            else:
                connection.execute(f"UPDATE cases SET {column} = ? WHERE county = ? AND index_number = ?",
                                   (candidate.value, COUNTY, result.index_number))
            existing = connection.execute(
                "SELECT method FROM field_sources WHERE county = ? AND index_number = ? AND field = ?",
                (COUNTY, result.index_number, column)).fetchone()
            if existing and existing["method"] == "regex" or not existing:
                connection.execute(
                    """INSERT INTO field_sources (county, index_number, field, value, method, section, source_file, recorded_at)
                       VALUES (?,?,?,?,'regex',?,?,?)
                       ON CONFLICT (county, index_number, field) DO UPDATE SET value = excluded.value,
                           method = excluded.method, section = excluded.section,
                           source_file = excluded.source_file, recorded_at = excluded.recorded_at""",
                    (COUNTY, result.index_number, column, str(candidate.value), candidate.section,
                     candidate.source_file, stamp))
            result.fields[column] = candidate.value
        if appearances:
            # The appearance table is re-read whole from the saved page, so it replaces the
            # case's earlier rows (a corrected parse must not leave the old rows behind).
            connection.execute("DELETE FROM appearances WHERE county = ? AND index_number = ?",
                               (COUNTY, result.index_number))
        for row in appearances:
            connection.execute(
                """INSERT INTO appearances (county, index_number, appearance_date, part, justice, purpose, outcome)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT (county, index_number, appearance_date, purpose) DO UPDATE SET
                       part = excluded.part, justice = excluded.justice, outcome = excluded.outcome""",
                (COUNTY, result.index_number, row["appearance_date"], row["part"], row["justice"], row["purpose"],
                 row["outcome"]))
        result.appearances = len(appearances)
        for file_name, sections in result.files.items():
            connection.execute(
                """INSERT INTO case_files (county, index_number, file_name, file_sha256, sections, text_method, ingested_at)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT (county, file_name) DO UPDATE SET index_number = excluded.index_number,
                       file_sha256 = excluded.file_sha256, sections = excluded.sections,
                       text_method = excluded.text_method, ingested_at = excluded.ingested_at""",
                (COUNTY, result.index_number, file_name, file_hashes[file_name], ",".join(sections),
                 methods[file_name], stamp))
        complete = {"case_detail", "appearances", "efiled_documents"} <= result.sections
        result.status = "done" if complete else "partial" if result.sections else "needed"
        connection.execute("UPDATE cases SET drilldown_status = ?, drilldown_at = ? WHERE county = ? AND index_number = ?",
                           (result.status, stamp, COUNTY, result.index_number))
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("index_number", nargs="?", help="only this case, e.g. 713725/2021")
    parser.add_argument("--cases-dir", type=Path, default=CASES_DIR)
    parser.add_argument("--county", default="Queens", help='the county of the cases, as its calendar names it ("New York")')
    parser.add_argument("--no-ocr", action="store_true", help="use only the embedded text layer")
    args = parser.parse_args()
    global COUNTY
    COUNTY = args.county
    connection = connect()
    groups, ignored = group_files(args.cases_dir.expanduser(), args.index_number)
    results: list[CaseResult] = []
    for index_number, paths in sorted(groups.items()):
        result, candidates, appearances = read_case(index_number, paths, ocr=not args.no_ocr)
        hashes = {path.name: sha256_file(path) for path in paths}
        methods = {path.name: (page_texts(path, ocr=not args.no_ocr)[1] if path.suffix.lower() == ".pdf" else "html")
                   for path in paths}
        save_case(connection, result, candidates, appearances, hashes, methods)
        results.append(result)
    for result in results:
        flag = "" if result.on_calendar else "  (not on any ingested calendar; saved as inactive)"
        print(f"{result.index_number}: {result.status}, {result.appearances} appearances, "
              f"{len(result.fields)} fields{flag}")
        for file_name, sections in result.files.items():
            print(f"    {file_name.strip()}: {', '.join(sections)}")
    print(f"{len(results)} cases from {sum(len(r.files) for r in results)} files.")
    print(f"Updated {write_drilldown_todo(connection, COUNTY, REPORTS)}")
    if ignored:
        print(f"Skipped {len(ignored)} file(s) whose name does not start with an index number:")
        for path in ignored:
            print(f"    {path.name}")


if __name__ == "__main__":
    main()
