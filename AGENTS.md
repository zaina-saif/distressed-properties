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

# Every other state (RealAuction OH/FL/CO/TX, SRI Indiana, CivilView states, PA portals, SC, IL TJSC, CT, county lists KY/OK/WI, TX Bexar and Collin trustee notices, California county tax sales on Bid4Assets,
# NY Erie sheriff and NYC tax-lien sales). NY court auctions (Queens, Manhattan) are loaded by hand; this run reports per county when
# their files were last loaded and the next auction, geocodes them, adds Zestimates
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
| `nj-sale-refresh.yml` | 11:00 on the 1st and 15th | `pipeline.nj_sale_refresh` (Zillow paused: skipped unless a manual run sets `skip_zillow` false; cap 400) |
| `multistate-sale-refresh.yml` | Mondays 10:00 | `pipeline.multistate_refresh` (Zillow paused, as for NJ; cap 600) |
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
| Nassau | Each case's files saved from NYSCEF/WebCivil into one folder, named "<index>-<year> Notice_of_sales.pdf", "... Summons.pdf" and "... Appearance.pdf", loaded with `load_ny_court_pdfs --folder` | Notice of Sale as for Kings ("prem. k/a", a weekday before the date); a notice giving only Section/Block/Lot takes the street from its case's Summons ("Mortgaged Premises: ...", "Premises Address:", or a tax-lien case's "also known as and by street number: ..."), and a case with no Notice of Sale but an upcoming WebCivil auction is loaded from its Summons address and that date. Summons are matched by file name and only the premises line is read |
| Manhattan (New York County) cases | WebCivil's "Court Calendar Details" for the Foreclosure Auction Part plus each case's summons, Notice of Sale and appearances, through `queens_pipeline/` (`ingest_calendar.py`, `ingest_case_files.py --county "New York"`), loaded with `python -m pipeline.load_queens_pipeline --county "New York"` | As for Queens, plus the auction time and the clerk's remarks ("CANCELED VIA EMAIL ...") |
| Queens and the other WebCivil counties | No auction list is published; `pipeline.queens_foreclosure_refresh --assisted --county <name>|all` collects calendars and NYSCEF Notices of Sale for New York, Kings, Queens, Bronx, Richmond, Nassau, Suffolk, Westchester, Orange, Onondaga and Erie (see `docs/queens-foreclosures.md`). The local `queens_pipeline/` (weekly calendar plus saved case files) loads with `python -m pipeline.load_queens_pipeline` | Index no., premises, calendar dates, block/lot, approximate judgment, referee, plaintiff's attorney, unpaid principal, WebCivil auction history |

WebCivil Appearance pages saved with the PDFs add each past auction outcome to the listing's history and, when the court calendar shows a later auction with no outcome yet, move the listing to that date as `scheduled`.

Every listing `load_queens_pipeline` loads also gets a case summary (`ny_court_case_summaries`, migration 043, built by `pipeline/ny_case_summary.py`): the summons, Notice of Sale, appearances and auction calendar in one view with the case's stages in order, served by `app/api/court_cases.py` (rebuilt with the day's date from the stored inputs, migration 045) and opened from the dashboard in place of the sale page (`has_case_summary`). Corrections, exclusions (multi-parcel sales) and PLUTO-checked addresses live in `load_queens_pipeline` keyed by (county, index number). Timeshare interests are listed without a value: `properties.valuation_excluded_reason` (migration 044), which the Zillow and NYC DOF stages skip and the dashboard shows as "Not valued". `python -m pipeline.flag_timeshares` sets it on any listing whose address or notice says timeshare (Atlantic County's Fairway Villas and Skyline Tower) and retires its Zillow results and valuations; both refreshes run it after loading.

NYC listings Zillow has no Zestimate for get the city's market value: `python -m pipeline.load_nyc_dof_values [--counties Queens] [--dry-run]` (NYC Open Data `8y4t-faws`, summed over the listing's lots, stored as provider `nyc_dof_market_value`; the API uses it for value and equity only while there is no Zestimate, and the dashboard labels it NYC DOF).

Listings use `source_system='ny_court_foreclosure_auction'`, keyed by index number (reruns update, never duplicate); the BBL goes in `property_number`, and the referee, auction details and judgment in `description_text` (shown as the notice details). The approximate judgment is the minimum-bid proxy, or, when a notice states only an "approximate amount of lien", that amount (`notice_lien_amount`, shown as basis `notice_lien`): the plaintiff sets the real opening bid at the sale. Winning bidders pay a 10% deposit. Adjournments are frequent: a postponement notice records the earlier date as `adjourned`, and a past auction date with no published result becomes `sold_or_cancelled_unverified`. Records that fail validation go to `<run-dir>/ny_court_parse_failures.json` (default `.local/ny-court-pdfs/runs/`) and are never loaded; OCR text is cached by file hash in `.local/ny-court-pdfs/`.

### California county tax sales

California counties' treasurer-tax collectors auction tax-defaulted property (five years unpaid) once or twice a year, most of them online on Bid4Assets. `pipeline.scrape_ca_tax_sales` finds every California storefront on Bid4Assets' County Tax Sales calendar (timeshare-only sales left out), reads each sale's parcels from the storefront's `/api/storefront/auctions/index` (APN, minimum bid, open and close times) and each open parcel's auction page for its address (cached in `.local/ca-tax-sales/`); `pipeline.load_ca_tax_sales` loads them per county as `source_system='ca_bid4assets_tax_sale'`, status `scheduled`, the minimum bid as the opening bid, APN in `map_number`, auction id in `property_number`, sale type "Tax-defaulted property sale" (the "Tax sales" filter). Parcels without a street address (mostly vacant land) are not loaded. Both run in the Monday multistate refresh; a county's storefront is picked up once Bid4Assets links it on the calendar. California mortgage foreclosures are private trustee sales with no public county list and are not collected.

### Texas trustee sales (Harris, Bexar, Collin and Fort Bend counties)

Most Texas mortgage foreclosures are non-judicial **trustee sales** on the first Tuesday of the month; the Notice of Trustee's Sale is filed with the county clerk at least 21 days before. The Harris County Clerk lists the notices by sale month (`FRCL_R.aspx`, an ASP.NET form without a CAPTCHA) and serves each as a scanned PDF, so the collector OCRs them with macOS Vision and runs on the operator's Mac (not in the scheduled refresh), monthly once the next sale's notices are in:

```bash
python -m pipeline.scrape_harris_trustee_notices [--limit 40] [--no-ocr]   # every upcoming sale month
python -m pipeline.match_hcad_legal --build     # yearly: HCAD PDATA parcel index (owner fields left out) in .local/hcad/<year>/
python -m pipeline.load_tx_trustee_sales [--dry-run]

# Bexar: the County Clerk's foreclosure map (ArcGIS, no OCR); part of the Monday multistate refresh
python -m pipeline.scrape_bexar_trustee_notices
python -m pipeline.load_tx_trustee_sales --input data/sheriff_sales/tx_bexar_trustee_notices.json

# Collin: the County Clerk's foreclosure notices site (Blazor app, read with a headless browser; locally
# SCRAPER_BROWSER_CHANNEL=chrome); part of the Monday multistate refresh, whose workflow installs Chromium
python -m pipeline.scrape_collin_trustee_notices
python -m pipeline.load_tx_trustee_sales --input data/sheriff_sales/tx_collin_trustee_notices.json

# Fort Bend: the County Clerk's monthly list (one scanned PDF per sale, posted by the 20th); macOS OCR page by page
# (about 10 s a page, cached), so run on the operator's Mac each month like Harris; --text-layer reads the rougher text on any OS
python -m pipeline.scrape_fort_bend_trustee_notices
python -m pipeline.load_tx_trustee_sales --input data/sheriff_sales/tx_fort_bend_trustee_notices.json
```

PDFs and OCR text (with borrowers' names) stay in `.local/harris-trustee-notices/`; the snapshot `data/sheriff_sales/tx_harris_trustee_notices.json` keeps only parsed property, sale and lender fields (`pipeline/parse_tx_trustee_notice.py`: address labeled or inferred, legal description with lot/block/subdivision, original loan amount, lender, association-lien flag). Listings use `source_system='tx_county_clerk_trustee_sale'`, keyed by the clerk's document number (`FRCL-YYYY-N`), status `scheduled_unverified` (read as `date_passed_unverified` after the sale day; the clerk publishes no results), sale type "Trustee sale (non-judicial foreclosure)", and the notice facts in `description_text`. The original loan amount is not a judgment or an opening bid, so no equity is shown. Notices with only a legal description take the site address of the one Harris Central Appraisal District parcel whose lot, block, subdivision and section match (`pipeline/match_hcad_legal.py`; OCR slips allowed only in long words, never a guess between two parcels); the HCAD account goes in `property_number` and the notice details say where the address came from. Metes-and-bounds tracts, condo units and unmatched notices are not loaded and are saved to `.local/harris-trustee-notices/without_address.json`. Bexar's map (`maps.bexar.org/arcgis/rest/services/CC/ForeclosuresProd/MapServer`, layer 0 Mortgage) gives each notice's document number, sale month, address and coordinates but no lender; its tax layer is left out. Collin's site (`apps2.collincountytx.gov/ForeclosureNotices`) gives address, sale and filing dates and property type, but no document number, so a notice is keyed by address, ZIP and sale date; entries the clerk titles only "FILED <date> - <month> SALE - <city>" have no address and are counted, not loaded. The collector reads until it has the total the page shows and keeps the last snapshot otherwise. Fort Bend's PDF is split where a page starts with a notice title or carries the clerk's file stamp ("2026 AUG 20 AM 10:34" or "FILED FOR RECORD ... AUG 18 2026", which also gives the filing date); notices are keyed by address, ZIP and sale date, and those with only a legal description are not loaded (no parcel matching for Fort Bend yet). Dallas (since Feb 2026) and Tarrant post notices only on `*.tx.publicsearch.us`, whose robots.txt disallows all automated access, so they are not collected. Trustee listings are `scheduled_unverified`, so the sale-probability model does not score them.

### STOX trustee sales (CA, AZ, AK, OR, UT)

STOX Posting and Publishing's sales calendar (`stox.quickbase.com`, app `bk42trzjg`, report "Today's Sales") lists trustee sales it posts for trustees such as Clear Recon. Its terms (section 13) forbid commercial use without written consent, which the operator obtained in October 2026. The day's report is exported by hand (`output/stox-todays-sales.json`) and loaded with `python -m pipeline.load_stox_trustee_sales --stox-consent` (without the flag it loads only into a local database). Listings use `source_system='stox_trustee_sale'`, keyed by STOX#, sale type "Trustee sale (non-judicial foreclosure)". Only the address, opening bid, trustee, state, county, sale date, postponed-to date, sales result and winning bid are stored; borrower names ("Executed By"), tax IDs, notes and contacts are not. A postponed sale is `scheduled` on its new date with the original date as `adjourned`; "Sold 3rd Party" and "Back to Beneficiary" are `sold` with the winning bid; a sale with neither is `sold_or_cancelled_unverified`.

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
