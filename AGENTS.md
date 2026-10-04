# AGENTS.md

Guidance for coding agents (Claude Code, Codex, and others) working in this repository. `CLAUDE.md` imports this file, so keep shared instructions here.

## What this is

A multi-state foreclosure/sheriff-sale data platform (started with Monmouth County, NJ). Python pipelines scrape sale listings and import public property records, a FastAPI API serves them, and a Next.js dashboard displays listings with valuations, equity, status history, lien pre-screening, and sale-probability explanations. `CODEX_CONTEXT.md` (core goals and parsing rules), `LIEN_CONTEXT.md` (lien engine spec), and `plan.md` (valuation coverage plan) hold the design intent; the code is the source of truth when they disagree.

## Commands

Backend (run from `backend/`, venv at `../.venv`):

```bash
source ../.venv/bin/activate
uvicorn app.main:app --reload            # API on :8000
pytest                                   # all tests (pytest.ini sets pythonpath=. and testpaths=tests)
pytest tests/test_normalize.py           # one file
pytest tests/test_normalize.py -k name   # one test
python -m pipeline.<module>              # every pipeline script is run as a module from backend/
psql "$DATABASE_URL" -f migrations/NNN_name.sql   # migrations are applied manually, in numeric order
```

Frontend (run from `frontend/`):

```bash
npm run dev     # next dev --webpack, http://localhost:3000
npm run build
npm run lint
```

Next.js here is v16 with breaking changes from older versions — read `frontend/AGENTS.md` and the guides in `node_modules/next/dist/docs/` before writing frontend code.

## Architecture

**Two databases** (`backend/app/database/session.py`):
- `DATABASE_URL` (Supabase Postgres) — operational data: sale listings, properties, status history, liens. Used by the API via `SessionLocal`.
- `WAREHOUSE_DATABASE_URL` (self-hosted Postgres) — large public assessment/sales history and AVM training data, via `WarehouseSessionLocal`. Statewide importers write here; don't point them at Supabase. When `WAREHOUSE_DATABASE_URL` is unset, the API and tests fall back to `DATABASE_URL`, but any `python -m pipeline.*` process refuses to connect the warehouse engine unless `ALLOW_WAREHOUSE_FALLBACK=1` is set.

**Pipeline** (`backend/pipeline/`), named by stage prefix:
- `scrape_*` fetch a source and write JSON snapshots to `backend/data/sheriff_sales/` (snapshots include `raw_payload`, `parser_version`, `status_history`).
- `load_*` read those snapshots into the operational DB. Loaders keep raw, content-hashed records and sale-status history, so parsing can be redone later without re-downloading.
- `import_*` bulk-load public property data (state/county assessment rolls, CAMA, deed transfers) into the warehouse. Most can be rerun safely or resumed (see flags like `--after-objectid` in README).
- `enrich_*`, `train_*` / `predict_*` (per-state XGBoost AVMs, sale-probability model), `calculate_equity` / `batch_calculate_equity`.
- Shared code: `adapters/` (per-source scrapers such as CivilView counties, Monmouth, NY county pages, PA Bid4Assets, all on `adapters/base.py`), `providers/` (external valuation providers, e.g. RentCast), `normalize.py`, `parse_sale_description.py`, `parcel_identity.py` / `resolve_parcel_identity.py` (canonical parcel IDs used to join listings to warehouse records).

Base NJ flow: `scrape_civilview` → `load_to_supabase` → `create_properties` (normalizes and deduplicates addresses) → `import_property_analysis_csv` (valuations and equity).

**Lien pre-screening** lives in `backend/app/liens/` (identity → source matching → risk/summary), exposed through `app/api/liens.py` including a lien-ingestion jobs router.

**API**: `app/main.py` mounts the properties, liens, lien-jobs, pa_data, and warehouse_valuations routers. `app/api/sheriff_sales.py` and `app/api/watchlists.py` exist but are **not mounted**. The frontend calls `${NEXT_PUBLIC_API_URL}/api/v1/...` through `frontend/src/services/properties.ts`. CORS allows only localhost:3000.

## Domain rules (from project specs)

- **Parsing financial figures:** judgment amount, upset price, and opening bid are different values; don't treat every dollar amount as the upset price. Keep both estimated and approximate upset figures and flag conflicts between them (`upset_price_conflict`). Never overwrite a reliable existing value with null, or a manually corrected value with a lower-confidence parse.
- **Equity:** `judgment_spread` = market value − judgment amount. It is not auction equity; don't label it that way. Use `Decimal` and handle null or zero values safely.
- **Valuations:** never invent a value just to fill a blank. Each estimate keeps its provider/method, range, confidence, and dates. If no reliable estimate exists, store an explicit review status. Paid third-party AVMs are deferred.
- **Liens:** this is a pre-screening tool only. Never present output as a title search, legal advice, or a guaranteed lien status. Priority results are `estimated_priority` with `priority_confidence` and `priority_reason`, and the UI shows a disclaimer that a professional title search is required.
- **Source honesty:** listings from secondary sources carry hedged statuses (e.g. `scheduled_unverified`, `date_passed_unverified`). Court/referee auctions are labeled as such, not as sheriff sales. Keep source URLs and raw data.
- **Privacy:** public-record importers deliberately exclude owner, mailing, grantor/grantee, and party fields. Keep it that way when adding importers.
- **Access controls:** collectors must not solve CAPTCHAs or bypass access controls. Sources that need a CAPTCHA (e.g. NY SalesWeb) use visible, operator-assisted runners. An access challenge should exit non-zero without importing stale data.

## Cloud agent environments

For Claude Code on the web, Codex cloud, or similar sandboxes:

- Setup: `python -m venv .venv && .venv/bin/pip install -r backend/requirements.txt && (cd frontend && npm ci)`.
- Secrets come from the environment settings, not committed files: `DATABASE_URL` plus the optional keys in `backend/.env.example` and `frontend/.env.local.example`.
- The warehouse database is self-hosted and not reachable from the cloud. Leave `WAREHOUSE_DATABASE_URL` unset there, so warehouse pipelines stop instead of writing to Supabase.
- Scrapers that need open internet access, and the operator-assisted collectors that need `.local/` browser profiles, run only on the operator's machine. In the cloud, stick to code, tests, and the API and frontend.

## Repo notes

- Two migrations share the number `014` (`014_pa_parcels.sql`, `014_property_search_indexes.sql`).
- Generated scrape outputs and logs in `backend/`, plus `.local/` and `tmp/`, are working data. `.local/` holds browser profiles and PDF caches for the assisted collectors.
- The README's "Implemented and planned areas" section is out of date: lien enrichment, sale prediction, and risk work have since been built.
