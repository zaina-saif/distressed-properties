I am building a sheriff-sale property analysis platform for Monroe County, Pennsylvania.

Tech stack:

* Frontend: Next.js
* Backend: Python FastAPI
* Database: PostgreSQL / Supabase
* Hosting: Vercel + Railway

The goal is to automatically collect Monroe County sheriff-sale properties, match them to county parcel data, enrich them with property information, and calculate investment metrics such as equity and risk.

## Data Sources

### 1. Monroe County Sheriff Sale Data

Use Monroe County's official sheriff real-estate-sale listings as the primary source for foreclosure properties.

Target fields:

* property number
* court case / docket number
* defendant / owner name
* property address
* map number / parcel number
* judgment amount
* attorney
* sheriff sale date
* sale status
* sale result, if available

The sheriff-sale records may be provided as PDFs, HTML tables, or downloadable documents.

Build the ingestion system so it can:

* download the latest sheriff-sale document
* extract all property rows
* normalize the data
* store the records in PostgreSQL
* avoid duplicates when rerun

Use the sheriff-sale `MAPNUMBER` / parcel identifier as the primary property-matching key whenever available.

Do NOT rely primarily on street-address matching.

---

### 2. PASDA Monroe County Parcel Data

Use Pennsylvania Spatial Data Access, PASDA, for the free Monroe County parcel GIS dataset.

ArcGIS REST service:

https://imagery.pasda.psu.edu/arcgis/rest/services/pasda/MonroeCounty/MapServer/1

The parcel dataset includes parcel geometry and a field such as:

`MAPNUMBER`

Use this field to join parcels to sheriff-sale records.

Build a Python importer that calls the ArcGIS REST API directly.

Prefer GeoJSON output where possible.

The importer should:

* query all parcel records
* handle ArcGIS pagination / record limits
* retrieve parcel geometry
* retrieve MAPNUMBER
* normalize MAPNUMBER formatting
* store parcel records in PostgreSQL / Supabase
* create latitude and longitude values from the parcel centroid if useful

Do not manually download the parcel file if the REST API can be queried programmatically.

---

### 3. Monroe County Assessment Data

Monroe County has a public property-search system that can be searched by:

* property number
* owner
* address
* map number

The free PASDA parcel dataset should NOT be assumed to contain:

* current owner
* assessed value
* property characteristics
* sale history

Treat assessment/property information as a separate enrichment source.

Before building automated scraping against the county assessment website:

* inspect whether the site exposes a public JSON/API endpoint
* inspect network requests used by the search page
* prefer an official API or structured endpoint over HTML scraping
* respect reasonable rate limits
* do not bypass authentication, CAPTCHA, access controls, or other restrictions

If bulk assessment data is not freely accessible, architect the system so enrichment can be added later without blocking the sheriff + parcel pipeline.

---

## Database Design

Create or update tables similar to:

### sheriff_sales

Fields:

* id
* property_number
* docket_number
* defendant_name
* property_address
* map_number
* judgment_amount
* attorney
* sale_date
* sale_status
* source_url
* created_at
* updated_at

### parcels

Fields:

* id
* map_number
* geometry
* latitude
* longitude
* source
* created_at
* updated_at

If PostGIS is available, use an appropriate geometry type.

Otherwise store GeoJSON in JSONB.

### property_details

Fields can include:

* map_number
* owner_name
* assessed_value
* land_value
* improvement_value
* property_type
* bedrooms
* bathrooms
* square_feet
* lot_size
* year_built
* last_sale_date
* last_sale_price
* enrichment_source
* last_updated

---

## Matching Logic

Primary join:

`sheriff_sales.map_number = parcels.map_number`

Normalize map numbers before matching.

Create one normalization function and use it everywhere.

The function should:

* trim whitespace
* uppercase values
* remove unnecessary formatting differences
* preserve meaningful parcel-number characters

Do not blindly remove characters if doing so could make two different parcel IDs identical.

Track:

* exact match
* normalized match
* unmatched

Do not silently fuzzy-match parcel numbers.

---

## Derived Fields

For matched parcels calculate or prepare fields for:

* latitude
* longitude
* parcel geometry
* estimated market value
* judgment amount
* estimated equity
* equity percentage
* sale status
* investment score
* risk score

Example:

estimated_equity =
estimated_market_value - judgment_amount

equity_percentage =
estimated_equity / estimated_market_value

Handle null values and division-by-zero safely.

Market-value enrichment can be implemented separately.

---

## API Endpoints

Create FastAPI endpoints such as:

GET /api/sheriff-sales

GET /api/sheriff-sales/{id}

GET /api/parcels/{map_number}

GET /api/properties/{map_number}

POST /api/admin/import/sheriff-sales

POST /api/admin/import/parcels

GET /api/admin/import/status

Support filters for:

* sale date
* municipality
* judgment amount
* estimated value
* equity
* sale status
* matched/unmatched parcel

---

## Import Architecture

Keep each ingestion source independent.

Suggested structure:

backend/
app/
ingestion/
sheriff_sales.py
pasda_parcels.py
assessment.py
services/
parcel_matching.py
property_enrichment.py
utils/
parcel_numbers.py
models/
api/

Each importer should be safe to rerun.

Use upserts rather than inserting duplicate records.

Log:

* rows downloaded
* rows parsed
* rows inserted
* rows updated
* rows skipped
* parsing errors
* unmatched parcel numbers

---

## First Implementation Priority

Implement this in phases.

### Phase 1

Get Monroe County PASDA parcels into PostgreSQL.

Create a working script that:

1. calls the ArcGIS REST endpoint
2. determines the available fields
3. retrieves every parcel using pagination
4. extracts MAPNUMBER and geometry
5. calculates parcel centroids if needed
6. stores the data in Supabase/PostgreSQL
7. prints import statistics

### Phase 2

Build the Monroe County sheriff-sale importer.

### Phase 3

Normalize parcel IDs and join sheriff sales to parcels.

### Phase 4

Investigate free assessment enrichment.

### Phase 5

Add market-value enrichment and investment calculations.

---

## Important Development Rules

Do not invent field names from the PASDA API.

First query the ArcGIS service metadata and inspect the real schema.

Do not assume pagination parameters without checking what the ArcGIS endpoint supports.

Do not overwrite existing working application functionality unnecessarily.

Inspect the current repository structure before creating new files.

Reuse existing:

* database clients
* environment variables
* Supabase setup
* FastAPI routers
* models

Keep credentials in environment variables.

Do not hardcode Supabase keys or database passwords.

Before making major changes, summarize:

* what already exists
* what you plan to add
* which files will change

Then implement Phase 1 first and verify that parcel records successfully appear in the database before moving on.
