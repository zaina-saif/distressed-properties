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

## Running the pipelines

Run everything from `backend/` with the venv active. The two refresh orchestrators are what keep the live site current; both send per-record output (which includes addresses) to `<run-dir>/refresh.log` and write counts to `<run-dir>/report.json`. The Zillow stage is paid (Apify), so use `--skip-zillow` for test runs.

```bash
# NJ: CivilView open + sold/cancelled for every NJ county, plus Ocean County's PDF.
# Stages: scrape load link zillow score report (default: all)
python -m pipeline.nj_sale_refresh --run-dir /tmp/nj-refresh --max-zillow-addresses 400
python -m pipeline.nj_sale_refresh --stages load link score report --skip-zillow   # rerun part of it

# Every other state (RealAuction OH/FL/CO/TX, SRI Indiana, CivilView states, PA portals, SC, IL TJSC, CT, county lists KY/OK/WI,
# NY Erie sheriff and NYC tax-lien sales). NY court auctions are loaded by hand; this run geocodes them, adds Zestimates
# (a missed Queens house is searched once more without the hyphen and with the town), gives NYC listings still without
# one the city's DOF market value (pipeline.load_nyc_dof_values) and marks their passed dates sold_or_cancelled_unverified.
# Stages: scrape load zillow score report. Default run dir: .local/multistate-refresh/
python -m pipeline.multistate_refresh --run-dir /tmp/ms-refresh --max-zillow-addresses 600

# Winning bids and buyers for sold sales (sold_amount / sold_buyer / sold_on; both refreshes run it after loading)
python -m pipeline.sale_results --dry-run

# Opportunity alert emails (needs RESEND_API_KEY, ALERTS_SIGNING_SECRET, ALERTS_POSTAL_ADDRESS)
python -m pipeline.send_opportunity_alerts --frequency daily --dry-run

# Free-trial emails: a reminder 2 days before a 7-day trial ends, and one when it ends (needs RESEND_API_KEY, ALERTS_POSTAL_ADDRESS)
python -m pipeline.send_trial_reminders --dry-run

# One source at a time: scrape, then load (the SOURCES list in multistate_refresh.py has every pair)
python -m pipeline.scrape_realauction --state OH --all && python -m pipeline.load_realauction_sales --state OH --all

# RealAuction past results (OH/FL sold, amount, buyer) into history/; --history loads them without retiring open sales
python -m pipeline.scrape_realauction --state OH --all --history-from 2025-10-01 && python -m pipeline.load_realauction_sales --state OH --all --history

# Indiana sheriff sales from SRI Services (public sriservices.com API); --history-from for past results
python -m pipeline.scrape_sri --all && python -m pipeline.load_sri_sales --all
python -m pipeline.scrape_sri --all --history-from 2025-10-01 && python -m pipeline.load_sri_sales --all --history

# Create or reset a developer login (needs SUPABASE_SERVICE_ROLE_KEY; trusted machine only)
python -m app.create_developer --email you@example.com
```

The sale-probability model the `score` stage uses is `backend/models/<MODEL_VERSION>.joblib`, built by `pipeline.train_sale_probability_model`. The `import_*` warehouse importers run by hand on the operator's machine, never in CI.

**Scheduled runs** (`.github/workflows/`, Python 3.12, `pip install -r requirements.txt` in `backend/`; each can also be started by hand with `workflow_dispatch`, with `skip_zillow` / `max_zillow_addresses` inputs):

| Workflow | Schedule (UTC) | Runs |
|---|---|---|
| `nj-sale-refresh.yml` | 11:00 on the 1st and 15th | `pipeline.nj_sale_refresh` (Zillow cap 400) |
| `multistate-sale-refresh.yml` | Mondays 10:00 | `pipeline.multistate_refresh` (Zillow cap 600) |
| `opportunity-alerts.yml` | daily 14:00 | `send_opportunity_alerts` daily, plus weekly on Mondays; then `send_trial_reminders` |

Their secrets are GitHub repository secrets: `DATABASE_URL`, `APIFY_API_TOKEN`, `RESEND_API_KEY`, `ALERTS_SIGNING_SECRET`, `ALERTS_POSTAL_ADDRESS`.

### Scraping framework and CLI

`backend/main.py` runs any registered scraper; `pipeline/scraping/` holds the shared pieces new collectors should use:

```bash
python main.py list                          # every registered scraper, by state
python main.py scrape nj                     # all statewide scrapers for a state (scrape + load)
python main.py scrape county "bergen"        # scrapers covering one county; add --state XX for "any county" sources (IN SRI)
python main.py scrape county "queens" --assisted   # visible browser; the operator passes any check
python main.py scrape ok --dry-run           # scrape and save snapshots only; load nothing
```

| Module | Role |
|---|---|
| `config.ScrapingSettings` | `SCRAPER_*` settings from `backend/.env` (see `.env.example`) |
| `challenge.detect_challenge` | Recognises interstitial/block pages (Cloudflare, Akamai, CAPTCHA prompts); a page that only embeds a CAPTCHA widget or a vendor script is not one |
| `rate_limit` | Per-host pacing (robots.txt `Crawl-delay` wins when larger), robots.txt per RFC 9309, exponential backoff |
| `http.PoliteClient` | `httpx.Client` drop-in: pacing, robots, retries on 429/5xx/timeouts, `AccessChallenge` (never a retry) on a challenge |
| `browser.BrowserManager` | Playwright Chromium; headless runs stop at a challenge, `--assisted` runs notify the operator, wait, then save the session |
| `sessions.SessionManager` | Saved storage state per site in `.local/sessions/` (0600), reused until expired |
| `monitoring.ScrapeMonitor` | `.local/scrape-artifacts/<run>/`: `responses.jsonl` (no cookies), HTML + screenshots of challenges/timeouts, `errors.jsonl`, `commands.log` |
| `base` | `SaleRecord` (common record), `ScraperBase` (native scraper loaded via `load_sales`), `CommandScraper` (an existing scrape/load module pair), the registry, `DatabaseManager` (a `scrape_runs` row per CLI run, `job_name` `cli:<scraper>`) |
| `plugins/{nj,ny,pa,other_states}.py` | Registrations; add a source by registering it here |

There is deliberately no proxy rotation or per-site proxy pool, no stealth patching and no hiding of the automation flags: `SCRAPER_PROXY_URL` is one fixed egress proxy. A site that keeps challenging an automated browser after the operator passed is declining automation; use a manual export (like the NY court PDFs) instead.

`docker compose up -d db api` starts a local Postgres with `docker/postgres-init` (Supabase stand-ins: `anon`/`authenticated` roles and an `auth.users` table, then every migration) and the API; `docker compose run --rm scraper scrape sc` runs the CLI against it. Migration `039_production_schema_catchup.sql` adds the tables and columns production had gained outside the migrations (a no-op there), so a fresh database matches it.

### New York pipeline

New York foreclosures are court-ordered **referee auctions**, not sheriff sales, and the courts publish them as PDFs on nycourts.gov. Those pages (and WebCivil/NYSCEF on iapps.courts.state.ny.us) answer scripts with a Cloudflare check, and NYSCEF guest search has a CAPTCHA, so nothing downloads them automatically. The operator opens the pages in a normal browser, saves the PDFs into one folder, and runs the loader on the operator's machine (OCR uses macOS Vision via `pipeline/ocr_pdf_macos.swift`):

```bash
python -m pipeline.load_ny_court_pdfs --folder ~/Documents/SheriffSaleProject/Files_For_NY --dry-run   # counts, samples, failures
python -m pipeline.load_ny_court_pdfs --folder ~/Documents/SheriffSaleProject/Files_For_NY
```

| Borough | What to save | Parsed |
|---|---|---|
| Brooklyn (Kings) | Every Notice of Sale PDF linked from https://www.nycourts.gov/courts/2nd-judicial-district/kings-county-supreme-court-civil-term/foreclosure-sales (auctions Thursdays) | Index no., premises, date/time/place, block/lot, approximate judgment, referee, plaintiff, plaintiff's attorney, postponements |
| Bronx | https://nycourts.gov/LegacyPDFS/courts/12jd/bronx/civil/pdfs/foreclosure-auctions.pdf (posted monthly; auctions Mondays) | Index no., premises, calendar date, block/lot, referee, plaintiff (no judgment) |
| Manhattan | The 1st JD Foreclosure Auction Part list | Index no., parties, outcome only: no addresses, so reported in the run dir, not loaded |
| Manhattan (New York County) cases | WebCivil's "Court Calendar Details" for the Foreclosure Auction Part plus each case's summons, Notice of Sale and appearances, through `queens_pipeline/` (`ingest_calendar.py`, `ingest_case_files.py --county "New York"`), loaded with `python -m pipeline.load_queens_pipeline --county "New York"` | As for Queens, plus the auction time and the clerk's remarks ("CANCELED VIA EMAIL ...") |
| Queens and the other WebCivil counties | No auction list is published; `pipeline.queens_foreclosure_refresh --assisted --county <name>|all` collects calendars and NYSCEF Notices of Sale for New York, Kings, Queens, Bronx, Richmond, Nassau, Suffolk, Westchester, Orange, Onondaga and Erie (see `docs/queens-foreclosures.md`). The local `queens_pipeline/` (weekly calendar plus saved case files) loads with `python -m pipeline.load_queens_pipeline` | Index no., premises, calendar dates, block/lot, approximate judgment, referee, plaintiff's attorney, unpaid principal, WebCivil auction history |

Every listing `load_queens_pipeline` loads also gets a case summary (`ny_court_case_summaries`, migration 043, built by `pipeline/ny_case_summary.py`): the summons, Notice of Sale, appearances and auction calendar in one view with the case's stages in order, served by `app/api/court_cases.py` and opened from the dashboard in place of the sale page (`has_case_summary`). Corrections, exclusions (multi-parcel sales) and PLUTO-checked addresses live in `load_queens_pipeline` keyed by (county, index number). Timeshare interests are listed without a value: `properties.valuation_excluded_reason` (migration 044), which the Zillow and NYC DOF stages skip and the dashboard shows as "Not valued".

NYC listings Zillow has no Zestimate for get the city's market value: `python -m pipeline.load_nyc_dof_values [--counties Queens] [--dry-run]` (NYC Open Data `8y4t-faws`, summed over the listing's lots, stored as provider `nyc_dof_market_value`; the API uses it for value and equity only while there is no Zestimate, and the dashboard labels it NYC DOF).

Listings use `source_system='ny_court_foreclosure_auction'`, keyed by index number (reruns update, never duplicate); the BBL goes in `property_number`, and the referee, auction details and judgment in `description_text` (shown as the notice details). The approximate judgment is the minimum-bid proxy, or, when a notice states only an "approximate amount of lien", that amount (`notice_lien_amount`, shown as basis `notice_lien`): the plaintiff sets the real opening bid at the sale. Winning bidders pay a 10% deposit. Adjournments are frequent: a postponement notice records the earlier date as `adjourned`, and a past auction date with no published result becomes `sold_or_cancelled_unverified`. Records that fail validation go to `<run-dir>/ny_court_parse_failures.json` (default `.local/ny-court-pdfs/runs/`) and are never loaded; OCR text is cached by file hash in `.local/ny-court-pdfs/`.

## Environment and config locations

Never commit secrets or print their values; the `.example` files list every setting with comments.

| Where | What |
|---|---|
| `backend/.env` (template `backend/.env.example`) | Loaded by `python-dotenv` in `app/database/session.py`. `DATABASE_URL`, `WAREHOUSE_DATABASE_URL`, `ALLOW_WAREHOUSE_FALLBACK`, `SUPABASE_URL` / `SUPABASE_ANON_KEY` / `SUPABASE_SERVICE_ROLE_KEY`, `STRIPE_*` (secret, webhook, four price IDs), `FRONTEND_URL`, `RESEND_API_KEY` / `CONTACT_*`, `ALERTS_*`, `APIFY_API_TOKEN`, `REALIE_API_KEY`, `GOOGLE_MAPS_API_KEY`, `CORS_ALLOWED_ORIGINS` / `CORS_ALLOWED_ORIGIN_REGEX`, `ENABLE_WAREHOUSE_API`, `SODA_ENDPOINTS_JSON` / `ARCGIS_TAX_ENDPOINTS_JSON`, `TITLE_SEARCH_PROVIDER_*` |
| `frontend/.env.local` (template `frontend/.env.local.example`) | `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` (publishable key only), `NEXT_PUBLIC_GEOAPIFY_API_KEY`. Compiled in at build time. |
| `backend/app/config.py` | API settings read from the environment |
| `backend/data/*_sheriff_sale_sources.json` | Source lists per state (NJ, NY, PA) |
| `backend/data/sheriff_sales/` | Scraped JSON snapshots |
| `backend/models/` | Trained model artifacts (sale probability, AVMs) |
| `backend/migrations/NNN_*.sql` | Schema, applied by hand in order with `psql` |
| `backend/railway.json`, `frontend/railway.json` | Railway build/deploy config (Dockerfile builder; health checks `/health` and `/`) |
| `.local/` | Browser profiles, PDF caches and refresh run dirs for local runs |

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

Other states load complete snapshots of each county's upcoming sales through `sale_listing_loader.load_sales`, which also marks open sales missing from a snapshot `sold_or_cancelled_unverified`: `scrape_realauction`/`load_realauction_sales` (OH sheriff sales, FL clerk sales, CO Public Trustee sales, TX sheriff/constable property-tax sales, which carry a redemption-period warning in the UI), `scrape_civilview_states`/`load_civilview_states` (non-NJ CivilView counties: DE, PA Philadelphia/Montgomery/Lehigh, IL Lake, some TX/GA), `scrape_sri`/`load_sri_sales` (IN sheriff sales from SRI Services, with coordinates, judgment and sale price), `scrape_sc_master_in_equity`/`load_sc_master_in_equity`, `scrape_county_sale_lists`/`load_county_sale_lists` (lists published by the selling office, keyed by state and county: KY Jefferson master commissioner CSV, OK Oklahoma and WI Milwaukee sheriffs on Bid4Assets, OK Tulsa sheriff via Tinstar, SD Minnehaha sheriff text list, WI Dane sheriff; add a county with one entry in `COUNTIES` and `SOURCES`. Tinstar's endpoint also returns buyers' contact details: keep only `TULSA_FIELDS`), and `scrape_pa_sale_listing`/`load_pa_sales`. New listings get missing ZIPs and coordinates from `fill_missing_zips` (free US Census geocoder; fills only empty values, one exact house-number match; both refreshes run it before Zillow; `--coordinates` locates listings that have a ZIP but no map position), then Zestimates and photos from `apify_scheduled_zillow` (paid; `--only-missing`, then `--retry-unmatched`; rows with a "0" street number or several addresses are skipped) and probabilities from the sale-probability model's `score_current`.

**Lien pre-screening** lives in `backend/app/liens/` (identity → source matching → risk/summary), exposed through `app/api/liens.py` including a lien-ingestion jobs router.

**API**: `app/main.py` mounts the properties, liens, lien-jobs, pa_data, and warehouse_valuations routers. `app/api/sheriff_sales.py` and `app/api/watchlists.py` exist but are **not mounted**. The frontend calls `${NEXT_PUBLIC_API_URL}/api/v1/...` through `frontend/src/services/properties.ts`. CORS allows localhost:3000 unless `CORS_ALLOWED_ORIGINS` says otherwise (see Hosting).

## Domain rules (from project specs)

- **Parsing financial figures:** judgment amount, upset price, and opening bid are different values; don't treat every dollar amount as the upset price. Keep both estimated and approximate upset figures and flag conflicts between them (`upset_price_conflict`). Never overwrite a reliable existing value with null, or a manually corrected value with a lower-confidence parse.
- **Equity:** `judgment_spread` = market value − judgment amount. It is not auction equity; don't label it that way. Use `Decimal` and handle null or zero values safely.
- **Valuations:** never invent a value just to fill a blank. Each estimate keeps its provider/method, range, confidence, and dates. If no reliable estimate exists, store an explicit review status. Paid third-party AVMs are deferred.
- **Liens:** this is a pre-screening tool only. Never present output as a title search, legal advice, or a guaranteed lien status. Priority results are `estimated_priority` with `priority_confidence` and `priority_reason`, and the UI shows a disclaimer that a professional title search is required.
- **Source honesty:** listings from secondary sources carry hedged statuses (e.g. `scheduled_unverified`, `date_passed_unverified`). Court/referee auctions are labeled as such, not as sheriff sales. Keep source URLs and raw data.
- **Privacy:** public-record importers deliberately exclude owner, mailing, grantor/grantee, and party fields. Keep it that way when adding importers.
- **Access controls:** collectors must not solve CAPTCHAs or bypass access controls. Sources that need a CAPTCHA (e.g. NY SalesWeb) use visible, operator-assisted runners. An access challenge should exit non-zero without importing stale data.

## Hosting

`DEPLOYMENT.md` covers production. Both services run on Railway in one project and deploy automatically on every push to `main` (a build takes a few minutes): the API (`api.sheriffsalehunter.ai`) from `backend/Dockerfile` with `backend/railway.json`, and the frontend (`www.sheriffsalehunter.ai`) from `frontend/Dockerfile` with `frontend/railway.json`. Production env vars are set in each Railway service's Variables, not in files; the frontend's `NEXT_PUBLIC_*` values are baked in at build time, so changing them needs a redeploy. To check a deploy: `gh api repos/zaina-saif/distressed-properties/commits/<sha>/status` shows Railway's status per service. Data refreshes run in GitHub Actions (see Running the pipelines). The API's allowed browser origins come from `CORS_ALLOWED_ORIGINS` / `CORS_ALLOWED_ORIGIN_REGEX`, and `ENABLE_WAREHOUSE_API=0` drops the warehouse routes on hosts that cannot reach the warehouse.

**Access control** (`backend/app/auth.py`, `app/api/account.py`): Supabase Auth tokens are verified against the project's JWKS (`SUPABASE_URL`); `user_accounts` holds role, plan and coverage (Trial all states for 7 days, once per account, no card; Free one county, Starter one state, Pro all; `role = developer` sees everything and manages users at `/admin/users` (`app/api/admin.py`: role and plan changes, logged in `user_access_changes`, migration 042); `role = file_uploader` gets the file storage only, no sale data and no plans). The front page's free-trial button goes to `/get-started?plan=trial`, which starts the trial on sign-in; an ended trial leaves the account without access until it picks a plan. Data routes depend on `require_access` / `require_property_access` and must apply the user's `scope_state` / `scope_county`; maintenance routes use `require_developer`; only aggregate facets are public. The private PDF storage (`/files` page, `app/api/files.py`, table `developer_files` from migration 041) keeps uploaded PDFs, single or unpacked from zips, in Postgres (downloadable one by one or all as one zip), deduplicated by SHA-256 per uploader; `require_file_access` lets developers (every file) and file uploaders (their own files) use it. Stripe Checkout and its webhook set plans. Every table in `public` has RLS on with no access for the `anon`/`authenticated` roles (migration 034), because the browser holds the publishable key: keep RLS on for new tables and never query data from the browser with Supabase.

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
