"""SQLite schema and connection for the NY court foreclosure pipeline (Queens first).

Every table is keyed by county, so other NY counties need no schema change.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DB_PATH = DATA / "sheriffsale.db"

SCHEMA = """
-- One row per court case. Key: county + index number.
CREATE TABLE IF NOT EXISTS cases (
  county               TEXT NOT NULL,
  index_number         TEXT NOT NULL,
  cms_index            TEXT,
  caption              TEXT,
  plaintiff            TEXT,
  defendant            TEXT,
  plaintiff_attorney   TEXT,
  defendant_attorney   TEXT,
  justice              TEXT,
  case_status          TEXT,
  filing_date          TEXT,
  referee_name         TEXT,
  property_address     TEXT,
  city                 TEXT,
  zip                  TEXT,
  borough_block_lot    TEXT,
  unpaid_principal     REAL,
  approximate_judgment REAL,
  approximate_lien_amount REAL,
  original_mortgagee   TEXT,
  initiating_doc       TEXT,
  initiating_doc_date  TEXT,
  lifecycle            TEXT NOT NULL DEFAULT 'active',
  first_seen_snapshot  INTEGER,
  last_seen_snapshot   INTEGER,
  times_scheduled      INTEGER NOT NULL DEFAULT 0,
  drilldown_status     TEXT NOT NULL DEFAULT 'needed',
  drilldown_at         TEXT,
  PRIMARY KEY (county, index_number)
);

-- One row per scheduled auction. Key: county + index number + auction date.
CREATE TABLE IF NOT EXISTS auction_events (
  county               TEXT NOT NULL,
  index_number         TEXT NOT NULL,
  auction_date         TEXT NOT NULL,
  court                TEXT,
  part                 TEXT,
  court_date_type      TEXT,
  fully_virtual        TEXT,
  purpose              TEXT,
  outcome              TEXT,
  event_status         TEXT NOT NULL,
  first_seen_snapshot  INTEGER NOT NULL,
  last_seen_snapshot   INTEGER NOT NULL,
  PRIMARY KEY (county, index_number, auction_date),
  FOREIGN KEY (county, index_number) REFERENCES cases(county, index_number)
);

-- Every calendar file ingested.
CREATE TABLE IF NOT EXISTS calendar_snapshots (
  snapshot_id          INTEGER PRIMARY KEY AUTOINCREMENT,
  county               TEXT NOT NULL,
  court                TEXT,
  part_selected        TEXT,
  calendar_created_at  TEXT,
  date_range_start     TEXT,
  source_file          TEXT NOT NULL,
  file_sha256          TEXT NOT NULL UNIQUE,
  row_count            INTEGER,
  ingested_at          TEXT NOT NULL
);

-- Raw rows per snapshot, kept for audit and re-processing.
CREATE TABLE IF NOT EXISTS snapshot_rows (
  snapshot_id          INTEGER NOT NULL REFERENCES calendar_snapshots(snapshot_id),
  county               TEXT NOT NULL,
  index_number         TEXT NOT NULL,
  auction_date         TEXT NOT NULL,
  raw_text             TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS appearances (
  county TEXT NOT NULL, index_number TEXT NOT NULL,
  appearance_date TEXT, part TEXT, justice TEXT, purpose TEXT, outcome TEXT,
  UNIQUE (county, index_number, appearance_date, purpose)
);

CREATE TABLE IF NOT EXISTS efiled_documents (
  county TEXT NOT NULL, index_number TEXT NOT NULL,
  doc_number INTEGER, doc_type TEXT, filed_date TEXT, description TEXT,
  UNIQUE (county, index_number, doc_number)
);

CREATE TABLE IF NOT EXISTS change_log (
  snapshot_id INTEGER NOT NULL, county TEXT NOT NULL, index_number TEXT NOT NULL,
  change_type TEXT NOT NULL,
  detail TEXT, logged_at TEXT NOT NULL
);

-- Case files read by ingest_case_files.py: which sections each file holds.
CREATE TABLE IF NOT EXISTS case_files (
  county TEXT NOT NULL, index_number TEXT NOT NULL,
  file_name TEXT NOT NULL, file_sha256 TEXT NOT NULL,
  sections TEXT NOT NULL,          -- comma-separated section names
  text_method TEXT NOT NULL,       -- embedded_text | macos_vision_ocr
  ingested_at TEXT NOT NULL,
  PRIMARY KEY (county, file_name)
);

-- Where each drill-down value came from. A regex value is never replaced by an LLM value.
CREATE TABLE IF NOT EXISTS field_sources (
  county TEXT NOT NULL, index_number TEXT NOT NULL,
  field TEXT NOT NULL, value TEXT,
  method TEXT NOT NULL,            -- regex | llm
  section TEXT NOT NULL,           -- the section the value was read from
  source_file TEXT NOT NULL,
  recorded_at TEXT NOT NULL,
  PRIMARY KEY (county, index_number, field)
);
"""
# Columns added after the first release, for databases created before them.
ADDED_COLUMNS = {"cases": {"approximate_judgment": "REAL", "approximate_lien_amount": "REAL"}}


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, isolation_level=None)  # explicit BEGIN/COMMIT
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(SCHEMA)
    for table, columns in ADDED_COLUMNS.items():
        present = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
        for name, kind in columns.items():
            if name not in present:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")
    return connection


def county_of(court: str | None) -> str:
    """'Queens Supreme Court' -> 'Queens'."""
    if not court:
        raise ValueError("The calendar does not name its court.")
    return court.replace("Supreme Court", "").replace("County", "").strip()
