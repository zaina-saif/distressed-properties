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

Set `DATABASE_URL` in `.env` for operational data (and Supabase-backed API
access). Set `WAREHOUSE_DATABASE_URL` to a self-hosted PostgreSQL database for
large public-history and AVM datasets:

```env
DATABASE_URL=postgresql+psycopg2://USER:PASSWORD@SUPABASE_HOST:5432/postgres
WAREHOUSE_DATABASE_URL=postgresql+psycopg2://LOCAL_USER@localhost:5432/sheriff_sale_warehouse
```

Initialize a new operational PostgreSQL database with:

```bash
psql "$DATABASE_URL" -f migrations/001_initial_schema.sql
```

Apply the remaining numbered migrations in order for multistate data, parcel
coordinates, valuation features, and indexed dashboard search.

For the warehouse, apply the public-history schema and then import Maryland:

```bash
psql "postgresql://LOCAL_USER@localhost:5432/sheriff_sale_warehouse" \
  -v ON_ERROR_STOP=1 -f migrations/019_public_avm_history.sql
python -m pipeline.import_maryland_property_data
```

The Maryland importer uses `WAREHOUSE_DATABASE_URL`. The FastAPI application
and existing sheriff-sale pipelines continue using `DATABASE_URL`, so Supabase
authentication and operational records are unaffected.

For Maryland records with no combined street address, migration 023 adds an
explicit house-number-unavailable flag. The importer now falls back to the
official premise street/city/ZIP fields, rejecting `00000` as a house number.
After applying that migration, older blank-address snapshots can be updated
without overwriting existing addresses with:

```bash
psql "$WAREHOUSE_DATABASE_URL" -f migrations/023_address_house_number_status.sql
python -m pipeline.backfill_maryland_addresses
```

The backfill requires Maryland's public Socrata API to be accessible; if it
returns an access challenge, use an authorized CSV export from the Maryland
open-data portal with `python -m pipeline.backfill_maryland_addresses --file
/path/to/official-export.csv`. The adapter accepts the portal's display-name
column headers as well as API field names. It does not access the SDAT
property-search website.

The official Maryland parcel-boundary GIS service is another public source for
premise street components when Socrata is challenged. It fills only blank
warehouse situs addresses and can resume from a committed OBJECTID:

```bash
python -m pipeline.backfill_maryland_addresses --arcgis --page-size 1000
# If interrupted: add --after-objectid LAST_PRINTED_OBJECTID
python -m pipeline.backfill_maryland_addresses --arcgis-missing --page-size 100
# If interrupted: add --after-parcel LAST_PRINTED_PARCEL_ID
```

The second command checks still-blank 2026 account IDs against the same GIS
service, including records whose GIS combined address is present but whose
warehouse address is blank. It also fills city and ZIP without inventing a
street when only those fields are available. Unmatched parcels remain
explicitly unavailable.

To copy public-history rows already present in the operational database without
downloading them again:

```bash
python -m pipeline.migrate_public_history_to_warehouse
```

Import Washington, DC's official Integrated Tax System assessment extract,
residential/condominium/commercial CAMA characteristics, and property-sale
history with:

```bash
python -m pipeline.import_dc_property_data
```

The DC importer joins records using the District's SSL parcel identifier and
deliberately excludes owner, mailing, mortgage, and tax-billing fields. It is
safe to rerun because snapshots and transactions are upserted by stable source
keys.

Import the current Florida Department of Revenue statewide preliminary tax
roll and sales data files with:

```bash
python -m pipeline.import_florida_property_data --apply-migration
```

The Florida importer discovers all 67 county NAL assessment and SDF sales ZIP
files from the official DOR portal, streams them one county at a time, and uses
`public_import_files` to resume safely after interruption. It intentionally
omits owner, mailing, fiduciary, legal-description, and exemption fields. The
current portal download is the 2026 preliminary submission; older annual files
require a separate Florida DOR public-records request.

Import Ohio OGRIP's statewide public parcel view with:

```bash
python -m pipeline.import_ohio_property_data
```

This resumable importer covers all 88 counties and deliberately requests only
parcel identifiers, situs addresses, land use, and land area. OGRIP's public
statewide view does not expose valuation or transaction-history fields, so
those must be supplemented from county auditor and recorder sources.

The first Ohio county enrichment adapters use official Cuyahoga and Franklin
County bulk sources:

```bash
python -m pipeline.import_ohio_cuyahoga_cama
python -m pipeline.import_ohio_franklin_appraisal
```

Cuyahoga supplies current certified assessment/building summaries and the
transfer associated with each parcel. Franklin supplies current appraisal and
dwelling characteristics plus its complete published sales tables. Both
adapters exclude owner, grantee/grantor, and mailing fields.

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
### Summit County, Ohio CAMA enrichment

Load the Summit County Fiscal Office public parcel, assessment, appraisal, land,
dwelling, and sales exports into the warehouse (owner/mailing fields are excluded):

```bash
cd backend
python -m pipeline.import_ohio_summit_cama
```
### Virginia statewide public parcel attributes

Download and extract VGIN's 2026 Q2 `Virginia Parcels: Local Schema Tables`
File Geodatabase, then load every locality while excluding owner, mailing,
grantor, and grantee fields:

```bash
cd backend
python -m pipeline.import_virginia_local_schemas --gdb /path/to/Virginia_Parcel_Dataset_LocalSchemas_2026Q2.gdb
```

Some locality-schema records lack a situs street. The official Virginia DWR
public parcel layer supplies additional QPID-linked situs addresses, city, and
ZIP without owner or mailing fields. Apply migration 024 and import it with:

```bash
psql "$WAREHOUSE_DATABASE_URL" -f migrations/024_public_parcel_addresses.sql
python -m pipeline.import_virginia_parcel_addresses
# If interrupted: add --after-objectid LAST_PRINTED_OBJECTID
```

The estimated-price property list uses exact parcel-ID matches from either
address source for the selected year or earlier; it never substitutes an owner
mailing address for a property's situs address.
### Fairfax County, Virginia detailed enrichment

Load Fairfax County's weekly public DTA parcel, dwelling, land, assessment, and
all-sales tables:

```bash
cd backend
python -m pipeline.import_virginia_fairfax_dta
```
### Richmond City, Virginia assessment and transfer history

Load Richmond's monthly public assessor workbook (five assessment years) and
2015-current transfer workbook:

```bash
cd backend
python -m pipeline.import_virginia_richmond_assessor
```

### Illinois statewide transfer history

Load Illinois IDOR's statewide MyDec PTAX-203 transfer declarations. The adapter
requests only property and transaction attributes; party, agent, preparer,
organization, and mailing fields are excluded:

```bash
cd backend
python -m pipeline.import_illinois_mydec
```

### Hillsborough, Florida foreclosure-auction notices

The Hillsborough clerk's RealAuction calendar is the authoritative live sale
schedule, but it currently returns HTTP 403 to this collector. The initial
dashboard feed instead extracts address-bearing, future-dated foreclosure
auction notices from the public Business Observer Hillsborough notice index.
It is deliberately labeled `Foreclosure auction (published notice)` and
`scheduled_unverified`: a published notice is not confirmation that the clerk
has not cancelled or rescheduled the auction. It does not include tax-deed
auctions or notices without an explicit street address and case number.

```bash
cd backend
python -m pipeline.scrape_hillsborough_foreclosure_notices --pages 40
python -m pipeline.load_hillsborough_foreclosure_notices
```

The importer is idempotent by court case and retains each source URL and raw
notice. Check the clerk's calendar before acting on any sale.

### New York statewide assessment history

NYC's Department of Finance [auction page](https://www.nyc.gov/site/finance/vehicles/auctions.page)
has a real-property section, but its currently linked Sheriff notice is a
September 8, 2021 New York County auction. The notice has been captured in
`backend/data/sheriff_sales/nyc_dof_property_auctions.json`; load it with:

```bash
cd backend
python -m pipeline.load_nyc_dof_property_auctions
```

It is labeled `date_passed_unverified` and inactive: the PDF establishes an
auction notice, not that a sale occurred or what price was paid. The page does
not currently provide a current five-borough real-property auction feed.
The Kings County Supreme Court's September 17, 2026 foreclosure calendar also
links 27 address-named PDFs. The index snapshot can be loaded with:

```bash
cd backend
python -m pipeline.load_nyc_kings_court_foreclosures
```

Those entries are labeled **court foreclosure auctions**, not sheriff sales.
Their addresses are taken from the official PDF filenames and their date from
the court calendar. Eight PDFs were later supplied locally and OCR-reviewed;
load their case numbers, BBLs, ZIP codes, parties, and stated amounts with:

```bash
cd backend
python -m pipeline.load_nyc_kings_local_notices
```

The other 19 remain filename-only until their notices are available. The 1025
East 13th Street notice calls its dollar figure a **lien**, not a judgment, so
it is stored separately. The supplied 1070 East 73rd Street PDF is marked page
1 of 2 and needs the missing page checked. None of these notices proves a
completed auction or winning bid. One filename contains two addresses and
requires manual parcel review. The
court warns that listed properties may be stayed, withdrawn, or otherwise not
sold. The other borough court pages checked do not provide a comparably
accessible current property-level list, so NYC coverage remains incomplete.

For recurring Kings collection, schedule this one-shot command (for example,
every weekday morning). It discovers the current court date and PDF links,
downloads each notice, extracts embedded text or uses macOS Vision OCR,
checks for conflicting dates, and then updates the database only when every
PDF download completes:

```bash
cd backend
python -m pipeline.collect_nyc_kings_foreclosure_pdfs --load
```

Downloaded PDFs and extraction JSON are cached under `.local/nyc-kings-court-pdfs/`
outside Git. An access challenge returns exit code 2, does **not** import stale
data, and should alert the operator. As of September 17, 2026, the court site
returned a Cloudflare 403 to direct HTTP and to individual PDF requests from
automated Chrome. A visible Chrome session reached the directory once but was
subsequently challenged. The collector is tested, but unattended access is
**not yet working** from this environment; a reliable accessible route is
needed before scheduling it in production. A court feed or allowlisting is one
possible route, not a prerequisite for manually reading public PDFs. The
collector does not solve CAPTCHAs or bypass access controls.
The separate NYCTL referee tax-lien auction source
can be refreshed and loaded into the dashboard/list with:

```bash
cd backend
python -m pipeline.scrape_nyc_referee_sales
python -m pipeline.load_nyc_referee_sales
```

These are **referee auctions, not sheriff executions**. The importer checks all
five borough BBL prefixes, saves a source snapshot, and places map pins only
when NYC Planning GeoSearch returns the exact BBL. The dashboard's NY filter
shows source-specific counts, including zero-listing boroughs. This source is
not a comprehensive foreclosure calendar; sale dates can be cancelled or
stayed and must be checked against the source before bidding.

Load the official 2021-2025 ORPTS final assessment rolls for all New York cities
and towns outside New York City. The adapter requests only parcel identity,
situs, classification, and valuation fields; owner, mailing, exemption, and deed
fields are excluded:

```bash
python -m pipeline.import_new_york_assessment_rolls
```

Use `--years 2025` to load the newest roll first or `--years 2024 2023 2022 2021`
to backfill prior rolls.

The separate public NYS tax-parcel layer provides 2025 building characteristics
for counties that authorize publication (including Albany). Import Albany first:

```bash
python -m pipeline.import_new_york_parcels --counties Albany
```

Use `--counties Albany Erie Suffolk` for additional covered counties, or
`--all-public-counties` to enumerate and load every county currently shared by
the state layer. NYC boroughs use the layer's ten-digit SBL as the BBL join key;
other counties use SWIS plus print key. The
importer reads only public non-owner assessment fields and joins by exact SWIS
plus print key. It stores the 2025 assessment as a separate snapshot; the
Estimated Price explorer can use it to fill missing characteristics on later
snapshots, but never projects it back onto earlier years. Its bathroom field is
the official full-bath count, not full plus half baths. Blank source fields and
unmatched parcel IDs remain blank.

Load NYC ACRIS deed transactions by joining the official Real Property Master
and Legals datasets on document ID. Party records are not requested:

```bash
python -m pipeline.import_nyc_acris_sales --years 2025
```

SalesWeb requires an interactive CAPTCHA. Use the visible assisted runner; solve
the CAPTCHA yourself, then let it enter county/year searches and checkpoint the
official downloads:

```bash
python -m pipeline.download_new_york_salesweb --counties Albany --start-year 2020 --manual-search
```

After validating Albany, use `--all-counties`. SalesWeb's custom search controls
currently require manual county/date selection; in `--manual-search` mode the
runner handles the download and checkpoint after each prepared search. It never
solves or suppresses CAPTCHA. Import downloaded CSV/XLSX files with:

```bash
python -m pipeline.import_new_york_salesweb data/public/ny_salesweb/*.xlsx
```

### State-specific XGBoost property valuation models

After applying migration 021, train an independent leakage-safe model for each
covered jurisdiction. Sales in the latest 12 months are held out as the final
test set, the preceding 12 months are used for candidate selection, and property
snapshots must predate the sale year (the most structurally complete prior
snapshot is chosen, with recency breaking ties):

```bash
psql "$WAREHOUSE_DATABASE_URL" -f migrations/021_state_avm_models.sql
python -m pipeline.train_state_avms --states MD FL OH VA DC IL NY --sample-percent 10
python -m pipeline.train_state_avms --states NY IL --segment residential --sample-percent 10
```

The initial run uses a deterministic 10% parcel sample of 2020-to-current sales
to keep training bounded; use `--sample-percent 100` for a full retrain. It uses
the latest earlier qualifying sale as a feature when available, never the target
sale itself. Model reports include train/validation/test counts, held-out errors,
feature-history coverage, and validation permutation reliance scores (not causal
coefficients). Models are promoted only when untouched test MAE beats the
prior-training county-median baseline and at least half of held-out sales are
within 20% of sale price. Rejected and insufficient-data runs
remain recorded for audit and are not used for property estimates. A promoted
state model is still a screening estimate, not an appraisal or proof of equity.
The optional NY/IL residential candidates use only explicitly arm's-length sales
with a pre-sale residential class and a $25,000–$10 million sale price. NY is
limited to SalesWeb records (not NYC ACRIS); Illinois uses Cook Assessor and
MyDec records. The NY class may come from an earlier ORPTS assessment roll.
These candidates have separate versioned reports and score only
properties in their documented source/class scope when promoted. They do not
establish statewide coverage or fill missing property features.
Florida also has a lower-history repeat-sale county-index experiment:
`python -m pipeline.train_florida_repeat_sales --sample-percent 10`. It uses
only qualified improved-property transfers (codes 01/02) and evaluates March
2026 for selection, then April–May 2026 untouched. It remains **rejected**
until it beats the unchanged prior-sale benchmark and meets the accuracy gate;
it is not served as an individual property AVM.
The sheriff-sale list separately exposes `AVM–judgment spread` only when a
current property valuation and a positive judgment are both present; it is not
net or legal equity. Warehouse-to-sheriff-sale linkage still requires a verified
property identity before a state model's estimate can be attached to a listing.

### Cook County, Illinois detailed enrichment

Load 1999-current Cook County assessments, residential/condominium characteristics
and sales, plus current parcel addresses and coordinates:

```bash
cd backend
python -m pipeline.import_illinois_cook_assessor
```

### DuPage County, Illinois assessment snapshot

Load the unrestricted official 2025 finalized parcel assessment layer. Billing
and ownership fields are excluded:

```bash
cd backend
python -m pipeline.import_illinois_dupage_assessment
```

### Lake County, Illinois open parcels

Load the County's unrestricted weekly parcel IDs, situs addresses, and point
coordinates. Taxpayer fields are excluded:

```bash
cd backend
python -m pipeline.import_illinois_lake_parcels
```

### Will County, Illinois open parcels

Load the County's openly licensed current parcel PINs, polygon areas, and derived
centroids:

```bash
cd backend
python -m pipeline.import_illinois_will_parcels
```

### McHenry County, Illinois open parcels

```bash
cd backend
python -m pipeline.import_illinois_mchenry_parcels
```

### Kane County, Illinois 2025 parcels

```bash
cd backend
python -m pipeline.import_illinois_kane_parcels
```
### Madison County, Illinois parcel enrichment

Import the official Madison County parcel base (PIN, situs address, and parcel area only; owner and mailing fields are excluded):

```bash
cd backend
python -m pipeline.import_illinois_madison_parcels
```
