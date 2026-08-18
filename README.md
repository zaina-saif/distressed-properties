# NJ Sheriff Sale Platform

A Monmouth County sheriff-sale data pipeline with a PostgreSQL/Supabase-backed
FastAPI API and a Next.js dashboard.

## Repository layout

- `backend/app`: FastAPI routes and database connection setup.
- `backend/migrations`: versioned PostgreSQL schema files.
- `backend/pipeline`: scraping, normalization, loading, valuation, and equity tools.
- `backend/tests`: automated unit tests.
- `frontend/src`: Next.js App Router dashboard, API client, and shared types.

Generated scrape snapshots and review reports live in `backend/` for backward
compatibility, but are ignored by Git. The manually maintained
`property_analysis_input.csv` remains source-controlled as an input template.

## Backend setup

Commands below are run from `backend/`:

```bash
python -m venv ../.venv
source ../.venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Set `DATABASE_URL` in `.env`, then initialize a new PostgreSQL database:

```bash
psql "$DATABASE_URL" -f migrations/001_initial_schema.sql
```

Start the API:

```bash
uvicorn app.main:app --reload
```

Run tests:

```bash
pytest
```

## Pipeline

Run these commands from `backend/` in order:

```bash
python -m pipeline.scrape_civilview
python -m pipeline.load_to_supabase
python -m pipeline.create_properties
python -m pipeline.import_property_analysis_csv
```

The first command contacts CivilView and writes JSON snapshots. The loader keeps
raw, content-hashed scrape records and sheriff-sale status history. Property
creation normalizes and deduplicates addresses. The CSV importer adds valuations
and computes equity.

## Frontend setup

Commands below are run from `frontend/`:

```bash
npm install
cp .env.local.example .env.local
npm run dev
```

The dashboard runs at `http://localhost:3000` and expects FastAPI at the URL in
`NEXT_PUBLIC_API_URL`.

## Implemented and planned areas

Property listing, scraping, status history, manual valuations, and equity
analysis are implemented. Watchlists, lien enrichment, risk calculation, sale
prediction, and background workers remain explicit placeholders for future work.
