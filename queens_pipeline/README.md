# NY court foreclosure pipeline (Queens first)

A local pipeline over files the operator downloads by hand. Nothing here contacts
WebCivil, NYSCEF or nycourts.gov. Data lives in `data/` (git-ignored): the SQLite
database `data/sheriffsale.db`, the OCR cache, reports and the JSON export.
The spec is `docs/queens-pipeline-prompt.md`.

```bash
cd queens_pipeline
pip install -r requirements.txt          # or use the repo's .venv, which has them

# 1. Weekly WebCivil "Justice/Part Calendar Details" export
python ingest_calendar.py data/queens/calendars/CourtCalendar_2026-10-14.pdf
#    -> data/reports/queens_<date>_delta.md/.csv, data/reports/queens_drilldown_todo.csv

# 2. Case files saved per index number (appearances, notice of sale, summons, case detail, ...)
python ingest_case_files.py --cases-dir ~/Documents/SheriffSaleProject/Files_For_NY/QueensSupremeCourt
python ingest_case_files.py 713725/2021 --cases-dir ...      # one case

# 3. One JSON per active case
python export_json.py                     # -> data/queens/export/

pytest                                    # QUEENS_CASES_DIR=<folder> also runs the real-file test

# 4. Put every active case with an address on the live site (from backend/, writes to DATABASE_URL)
cd ../backend && python -m pipeline.load_queens_pipeline --dry-run && python -m pipeline.load_queens_pipeline
```

| File | Role |
|---|---|
| `calendar_parser.py` | WebCivil calendar PDF -> rows (pdfplumber keeps the reading order; pypdf does not) |
| `ingest_calendar.py` | Weekly delta: new/returning cases, new dates, outcome changes, dropped/passed events |
| `case_parsers.py` | Splits a case file into documents (WebCivil page title or NYSCEF stamp) and parses each |
| `pdf_text.py` | Embedded text, or macOS Vision OCR (`backend/pipeline/ocr_pdf_macos.swift`) for scanned pages, cached by hash |
| `ingest_case_files.py` | Fills case details, appearances and `field_sources` (where each value came from) |
| `export_json.py` | The per-case JSON |

Choices the spec left open, or where the real files differed from it:

- **Index numbers** can have four digits (`5393/2008`), so an entry starts at `^\d{3,6}/\d{4} - `.
- **File names** as saved (`705527- 2014  Notice_of_sales.pdf`, `710760:2021 Summons.pdf`) are accepted:
  spaces and `:` around the separator, then a space, `_` or `.`. The file name is never trusted for the
  content: two files named "summons"/"appearances" hold the other document.
- **A case stays active while it is on the calendar**, even when its only entry shows an outcome
  ("Not Held"); it goes inactive once it is off the calendar with nothing scheduled. Only `scheduled`
  events become `passed`/`dropped`. An event back on the calendar is logged as a new auction date.
- **Extra tables:** `case_files` (sections found in each file) and `field_sources` (section, file and
  method of every drill-down value). `borough_block_lot` is `4-<block>-<lot>` (several lots: `4-12073-429/430`).
- **Precedence:** Notice of Sale over the summons and complaint over a notice of pendency; among complaints
  the latest filing. `initiating_doc`, `initiating_doc_date` and `filing_date` come only from NYSCEF document 1.
- **Appearances** are read by word position (cells wrap over several lines). The spec's key
  (date + purpose) merges two hearings of the same kind on one day. A case's rows are replaced when its
  appearance page is re-read.
- **OCR** runs on pages with under 200 characters of text, first 25 pages of a file only.
- **Notice amounts:** "approximate amount of judgment" is the judgment; "approximate amount of lien" is kept
  apart as `approximate_lien_amount` and never used as the judgment.
- **Queens house numbers** printed without the hyphen before a numbered street (`15826 78th Avenue`), or with five
  digits (`12320 Grayson Street`), get it back; four digits before a named street stay as printed (`1654 George Street`).
  Addresses a filing prints wrongly or leaves out are corrected in `load_queens_pipeline.ADDRESS_CORRECTIONS`, checked
  against the lot's address in NYC PLUTO; `EXCLUDED` lists cases not put on the site (a multi-parcel, multi-borough sale).
- No LLM fallback is implemented; every value is a regex match (`method = 'regex'`).
