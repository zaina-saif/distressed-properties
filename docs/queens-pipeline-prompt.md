You are building a local data pipeline for sheriffsalehunter.ai. Start with ONE county: **Queens**. The design must work for other NY counties later without schema changes.

## Ground rules
- **Do not access WebCivil Supreme, NYSCEF, or any nycourts.gov site programmatically.** No HTTP requests, no Playwright, no scraping. All inputs are files I download by hand and place in the folders below. Your code only parses local files.
- Never invent data. If a field isn't in the source file, store NULL.
- Use Python 3.11+, SQLite (one file: `data/sheriffsale.db`), and `pdfplumber` for PDF text. Keep dependencies minimal and list them in `requirements.txt`.
- Before writing any parser, open the sample files I provide and inspect the real text layout. Build parsers from what you see, not from assumptions.

## Folder layout
```
data/
  sheriffsale.db
  queens/
    calendars/            # weekly WebCivil "Justice/Part Calendar Details" PDF exports
      CourtCalendar_2026-10-11.pdf
    cases/                # flat folder: pages I save by hand, one file per case
      713725-2021.pdf     # index number with "/" replaced by "-" (.pdf or .html)
      703843-2021.pdf
  reports/                # generated output
```

Case file naming:
- The file name is the index number with `/` replaced by `-` (e.g. `713725/2021` → `713725-2021.pdf`). Map it back by replacing the last `-` with `/`.
- One file per case usually holds everything I saved for that case (case detail, appearances, e-filed documents), printed or combined into one PDF or HTML file.
- If I save more than one file for a case, extra files take a suffix after the index number: `713725-2021_summons.pdf`, `713725-2021_2.pdf`. Treat every file whose name starts with `<index>` followed by `.` or `_` as belonging to that case.
- Ignore files that don't match this pattern, and list them in the run output.

## Input 1: the weekly calendar PDF (format is known)
The text from a real export looks like this:

```
WebCivil Supreme - Justice/Part Calendar Details
Calendar created on: October 11, 2026 at 10:53 AM
Court: Queens Supreme Court
Date Range: 10/11/2026 -
Part Selected: FORECLOSURE AUCTION PART
Friday, October 16, 2026
713725/2021 - US BANK NATIONAL ASSOCIATION vs. TELLO, JONNI R. ETAL
Queens Supreme Court / Part: FORECLOSURE AUCTION PART
CMS Index: 0017567/2009
Justice: (Master Foreclosure Part), MFJ
Fully Virtual: No / Court Date Type: Courtroom
Court Date Purpose: Auction-Foreclosed Property
Plaintiff Attorney: DRUCKMAN LAW GROUP PLLC
Defendant Attorney: ...
...
Page 1 of 20
```

Parsing rules:
- The header (`Calendar created on`, `Court`, `Date Range`, `Part Selected`) appears once, on page 1. Store it as snapshot metadata.
- Each page starts with the line `WebCivil Supreme - Justice/Part Calendar Details` and ends with `Page N of M`. Strip both, then join all pages into one text stream, because entries can split across page breaks.
- A date line (`Friday, October 16, 2026`) sets the auction date for every entry that follows it, until the next date line.
- An entry starts at a line matching `^\d{5,6}/\d{4} - `. Split the caption on ` vs. ` (only the first occurrence) into plaintiff and defendant.
- These fields are optional, so they may be missing from an entry: `CMS Index`, `Justice`, `Defendant Attorney`. The plaintiff or defendant name can also contain "vs.", so split on the first ` vs. ` only.
- The purpose line can carry an outcome: `Court Date Purpose: Auction-Foreclosed Property / Outcome: Not Held`. Split it into `purpose` and `outcome`.
- The same index number can appear on more than one date. In the sample, 708268/2023 and 717620/2023 each appear twice. Keep each pair as a separate auction event.
- Sanity check: the sample PDF (20 pages, created Oct 11, 2026) must parse to **183 rows, 181 unique index numbers, and 8 rows with Outcome: Not Held**. Write a test that asserts these counts.

## Schema

```sql
-- One row per court case. Key: county + index number.
CREATE TABLE cases (
  county               TEXT NOT NULL,
  index_number         TEXT NOT NULL,          -- e.g. '713725/2021'
  cms_index            TEXT,
  caption              TEXT,
  plaintiff            TEXT,
  defendant            TEXT,
  plaintiff_attorney   TEXT,
  defendant_attorney   TEXT,
  justice              TEXT,
  -- filled from drill-down files (NULL until then)
  case_status          TEXT,
  filing_date          TEXT,
  referee_name         TEXT,
  property_address     TEXT,
  city                 TEXT,
  zip                  TEXT,
  borough_block_lot    TEXT,
  unpaid_principal     REAL,
  original_mortgagee   TEXT,
  initiating_doc       TEXT,
  initiating_doc_date  TEXT,
  -- lifecycle
  lifecycle            TEXT NOT NULL DEFAULT 'active',  -- active | inactive
  first_seen_snapshot  INTEGER,
  last_seen_snapshot   INTEGER,
  times_scheduled      INTEGER NOT NULL DEFAULT 0,
  drilldown_status     TEXT NOT NULL DEFAULT 'needed', -- needed | done | partial
  drilldown_at         TEXT,
  PRIMARY KEY (county, index_number)
);

-- One row per scheduled auction. Key: county + index number + auction date.
CREATE TABLE auction_events (
  county               TEXT NOT NULL,
  index_number         TEXT NOT NULL,
  auction_date         TEXT NOT NULL,          -- ISO 'YYYY-MM-DD'
  court                TEXT,
  part                 TEXT,
  court_date_type      TEXT,
  fully_virtual        TEXT,
  purpose              TEXT,
  outcome              TEXT,                   -- e.g. 'Not Held', NULL if none shown
  event_status         TEXT NOT NULL,          -- scheduled | not_held | passed | dropped
  first_seen_snapshot  INTEGER NOT NULL,
  last_seen_snapshot   INTEGER NOT NULL,
  PRIMARY KEY (county, index_number, auction_date),
  FOREIGN KEY (county, index_number) REFERENCES cases(county, index_number)
);

-- Every calendar file ingested.
CREATE TABLE calendar_snapshots (
  snapshot_id          INTEGER PRIMARY KEY AUTOINCREMENT,
  county               TEXT NOT NULL,
  court                TEXT,
  part_selected        TEXT,
  calendar_created_at  TEXT,
  date_range_start     TEXT,
  source_file          TEXT NOT NULL,
  file_sha256          TEXT NOT NULL UNIQUE,   -- ingesting the same file twice is a no-op
  row_count            INTEGER,
  ingested_at          TEXT NOT NULL
);

-- Raw rows per snapshot, kept for audit and re-processing.
CREATE TABLE snapshot_rows (
  snapshot_id          INTEGER NOT NULL REFERENCES calendar_snapshots(snapshot_id),
  county               TEXT NOT NULL,
  index_number         TEXT NOT NULL,
  auction_date         TEXT NOT NULL,
  raw_text             TEXT NOT NULL
);

-- Drill-down detail tables.
CREATE TABLE appearances (
  county TEXT NOT NULL, index_number TEXT NOT NULL,
  appearance_date TEXT, part TEXT, justice TEXT, purpose TEXT, outcome TEXT,
  UNIQUE (county, index_number, appearance_date, purpose)
);

CREATE TABLE efiled_documents (
  county TEXT NOT NULL, index_number TEXT NOT NULL,
  doc_number INTEGER, doc_type TEXT, filed_date TEXT, description TEXT,
  UNIQUE (county, index_number, doc_number)
);

-- Change log: one row per change detected.
CREATE TABLE change_log (
  snapshot_id INTEGER NOT NULL, county TEXT NOT NULL, index_number TEXT NOT NULL,
  change_type TEXT NOT NULL,   -- new_case | returning_case | new_auction_date | outcome_changed | dropped_before_date | passed
  detail TEXT, logged_at TEXT NOT NULL
);
```

## Weekly delta logic (`ingest_calendar.py <pdf>`)
Run inside one transaction. Let `S` be the new snapshot and `D` its date range start (for example `Date Range: 10/11/2026`):

1. If the file's SHA-256 has already been ingested, print a message and stop.
2. Parse every row and insert it into `snapshot_rows`.
3. For each `(county, index_number)` in the snapshot:
   - **Not in `cases`:** insert it with `lifecycle='active'` and `drilldown_status='needed'`. Log `new_case`.
   - **In `cases` with `lifecycle='inactive'`:** set it back to active. Do not reset `drilldown_status`. Log `returning_case`.
   - **Already active:** update the calendar fields (attorneys, justice, CMS index) only when the new value is not NULL.
   - Set `last_seen_snapshot = S`.
4. For each `(county, index_number, auction_date)` in the snapshot:
   - **New:** insert it with `event_status='scheduled'`, or `'not_held'` if an outcome is shown. Increment `cases.times_scheduled`. Log `new_auction_date`.
   - **Already exists:** update `last_seen_snapshot`. If the outcome changed, update it and log `outcome_changed`.
5. Handle events that are active in the database but **not** in this snapshot, for this county:
   - If `auction_date < D`, set `event_status='passed'` and log `passed`. The sale date has come and gone.
   - If `auction_date >= D`, set `event_status='dropped'` and log `dropped_before_date`. The sale was removed early, which probably means it was cancelled or adjourned.
6. Any case with no `scheduled` events left gets `lifecycle='inactive'`. **Never delete cases or events.**
7. Write `data/reports/queens_<calendar date>_delta.md` and `.csv` with these sections: **New cases (need drill-down)**, Returning cases, New auction dates for known cases, Outcome changes, Dropped before date, Passed. Include counts at the top.
8. Also write `data/reports/queens_drilldown_todo.csv`, listing every active case with `drilldown_status='needed'`. Each row has the index number, the caption, the next auction date and the exact file name to save it as (e.g. `713725-2021.pdf`).

## Drill-down ingestion (`ingest_case_files.py [index_number]`)
- For each case file in `data/queens/cases/` (or only that index number's files, if one is given), group the files by index number. Detect which sections each file contains (case detail, appearances, e-filed documents, summons/complaint or notice of pendency) from the page text, not the file name. A single file may contain several sections, or all of them.
- **I will give you sample files first. Inspect them and build the parsers from their real layout.** Until I do, build a stub that only lists, for each index number, which files it found and which sections they appear to contain.
- Fill in the `cases` drill-down fields and the `appearances` and `efiled_documents` rows. Use upserts, so re-running is safe.
- Set `drilldown_status` to `done` when the case detail, appearances and e-filed documents are all parsed. Otherwise set it to `partial`.
- For the summons/complaint or notice of pendency section, extract the property address, block/lot, principal amount and original mortgagee with deterministic regexes first. If an LLM fallback is needed, put it behind a flag, store which method produced each value, and never overwrite a regex value with an LLM value.

## Export
`export_json.py` writes one JSON file per active case to `data/queens/export/`, matching this shape:
```json
{
  "county": "Queens",
  "index_number": "713725/2021",
  "court": "Queens Supreme Court",
  "court_part": "FORECLOSURE AUCTION PART",
  "scheduled_auction_date": "2026-10-16",
  "status": "Scheduled",
  "plaintiff": "US BANK NATIONAL ASSOCIATION",
  "defendant": "TELLO, JONNI R. ETAL",
  "property_details": { "address": null, "borough_block_lot": null, "unpaid_principal_balance": null },
  "referee_name": null,
  "plaintiff_attorney": "DRUCKMAN LAW GROUP PLLC",
  "times_scheduled": 1,
  "appearance_history": [],
  "efiled_documents_summary": { "initiating_doc": null, "filing_date": null }
}
```
`scheduled_auction_date` is the earliest event with `event_status='scheduled'`.

## Tests (pytest)
- Parsing the sample calendar gives 183 rows, 181 unique cases and 8 Not Held rows.
- Ingesting the same file twice changes nothing.
- A simulated next week tests every branch. Remove 3 cases, move 1 case to a new date, add 2 new cases, and re-add 1 inactive case. Check that the new, returning, passed, dropped and new-date counts are right, and that no row is ever deleted.

## Order of work
1. Create the project skeleton, schema and calendar parser, and pass the parser test against `data/queens/calendars/CourtCalendar_2026-10-11.pdf`.
2. Build the delta ingest and its tests.
3. Run it on the sample and show me the delta report. On the first run, all 181 cases should be new.
4. Stop and ask me for sample drill-down files before writing those parsers.
