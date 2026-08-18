PROJECT: NJ Sheriff Sale Lien Search + Property Risk Engine

OBJECTIVE

Extend the existing New Jersey Sheriff Sale property analysis platform with an automated lien-search and risk-analysis system.

The system should:

1. Accept a sheriff-sale property already stored in the database.
2. Identify the property's parcel/PAMS PIN and current owner(s).
3. Search or ingest publicly available lien-related records.
4. Normalize all lien records into a common database format.
5. Match liens to the correct property and/or owner.
6. Determine whether liens appear active, released, satisfied, discharged, redeemed, or unknown.
7. Analyze lien priority and potential sheriff-sale implications.
8. Generate a structured risk assessment.
9. Display the results in the existing property dashboard.
10. Preserve source URLs, timestamps, confidence scores, and raw source data for auditability.

IMPORTANT:
This system is a PRE-SCREENING tool only.

It must NOT claim to provide:
- certified title searches
- legal advice
- guaranteed lien status
- title insurance
- guaranteed post-sale lien liability

Every property should show a disclaimer that a professional title search/legal review is required before bidding.

--------------------------------------------------
1. EXISTING APPLICATION ARCHITECTURE
--------------------------------------------------

Assume the existing system uses:

Frontend:
- Next.js
- TypeScript
- React

Backend:
- Python
- FastAPI

Database:
- PostgreSQL
- Supabase

Existing core entity:
property

Properties may already contain fields such as:

id
address
city
county
state
zip
sale_date
sheriff_sale_id
case_number
plaintiff
defendant
judgment_amount
assessed_value
estimated_market_value
estimated_equity
sale_status

Extend the existing architecture rather than creating a disconnected application.

--------------------------------------------------
2. HIGH-LEVEL PIPELINE
--------------------------------------------------

Create the following pipeline:

Sheriff Sale Property
        |
        v
Property Identity Resolver
        |
        +--> Address normalization
        +--> PAMS PIN / parcel ID
        +--> Block
        +--> Lot
        +--> Qualifier
        +--> Municipality
        +--> County
        +--> Current owner
        +--> Historical owners
        |
        v
Public Record Data Collectors
        |
        +--> County land records
        +--> Mortgage records
        +--> Mortgage discharges
        +--> Lis pendens
        +--> Judgments
        +--> Tax sale certificates
        +--> Municipal liens where available
        +--> UCC records
        |
        v
Raw Records Store
        |
        v
Normalization Layer
        |
        v
Property / Owner Matching Engine
        |
        v
Lien Resolution Engine
        |
        +--> active
        +--> satisfied
        +--> discharged
        +--> released
        +--> redeemed
        +--> expired
        +--> unknown
        |
        v
Lien Priority Engine
        |
        v
Risk Scoring Engine
        |
        v
Property Risk Report
        |
        v
Next.js Dashboard

--------------------------------------------------
3. PROPERTY IDENTITY RESOLUTION
--------------------------------------------------

Create a service:

PropertyIdentityService

Input:

property_id

Output:

{
    property_id,
    normalized_address,
    county,
    municipality,
    block,
    lot,
    qualifier,
    pams_pin,
    current_owners,
    historical_owners,
    confidence_score
}

Address normalization should:

- uppercase consistently
- normalize STREET/ST, ROAD/RD, AVENUE/AVE, etc.
- strip punctuation
- normalize apartment/unit information
- normalize municipality names
- preserve original input
- produce a canonical search address

Example:

Original:
"182 Municipal Dr, East Stroudsburg, PA"

Canonical concept:
"182 MUNICIPAL DRIVE"

For NJ parcels, prioritize:

county
municipality
block
lot
qualifier
PAMS PIN

Parcel identifiers should be preferred over addresses whenever available.

Create fields on the property table if they do not already exist:

pams_pin
municipality_code
block
lot
qualifier
normalized_address
identity_confidence

--------------------------------------------------
4. DATA SOURCE ADAPTER ARCHITECTURE
--------------------------------------------------

Do NOT hard-code scraping logic directly into business logic.

Create an adapter architecture.

Base interface:

class LienSourceAdapter:

    async def search_property(self, property_identity):
        ...

    async def search_owner(self, owner):
        ...

    async def fetch_record_details(self, record):
        ...

    async def normalize_record(self, raw_record):
        ...

Every public-record source should implement this interface or a specialized derivative.

Example adapters:

CountyLandRecordsAdapter
JudgmentSearchAdapter
MunicipalTaxAdapter
TaxSaleCertificateAdapter
UCCAdapter

County implementations should be isolated.

Example:

CountyLandRecordsAdapter
    MonmouthCountyAdapter
    OceanCountyAdapter
    BergenCountyAdapter
    MiddlesexCountyAdapter
    EssexCountyAdapter
    etc.

This allows counties to have different search systems without changing the core lien engine.

--------------------------------------------------
5. DO NOT BYPASS ACCESS CONTROLS
--------------------------------------------------

The system must NOT:

- bypass CAPTCHAs
- defeat authentication
- evade rate limits
- circumvent access-control mechanisms
- simulate abusive traffic
- access non-public data

If a public system blocks automation:

Return:

source_status = "manual_review_required"

Provide the user with:
- source name
- source URL
- recommended search parameters
- owner name
- block/lot
- parcel ID

Design the source adapter so manual results can later be entered/imported.

--------------------------------------------------
6. RAW SOURCE DATA TABLE
--------------------------------------------------

Create:

raw_public_records

Fields:

id UUID PRIMARY KEY
property_id UUID NULL
source_name TEXT
source_type TEXT
source_url TEXT
source_record_id TEXT
search_type TEXT
search_query JSONB
raw_data JSONB
raw_html TEXT NULL
retrieved_at TIMESTAMP
source_last_updated TIMESTAMP NULL
ingestion_status TEXT
parser_version TEXT
content_hash TEXT

Use content_hash to avoid inserting identical records repeatedly.

--------------------------------------------------
7. NORMALIZED LIEN TABLE
--------------------------------------------------

Create:

property_liens

Fields:

id UUID PRIMARY KEY

property_id UUID
raw_record_id UUID NULL

lien_type TEXT
lien_subtype TEXT

status TEXT

status values:

ACTIVE
SATISFIED
DISCHARGED
RELEASED
REDEEMED
EXPIRED
POSSIBLY_ACTIVE
UNKNOWN

creditor_name TEXT
debtor_name TEXT

original_amount NUMERIC NULL
current_amount NUMERIC NULL

recording_date DATE NULL
effective_date DATE NULL
maturity_date DATE NULL
release_date DATE NULL

instrument_number TEXT NULL
book TEXT NULL
page TEXT NULL
docket_number TEXT NULL
case_number TEXT NULL

county TEXT
municipality TEXT

block TEXT NULL
lot TEXT NULL
qualifier TEXT NULL
pams_pin TEXT NULL

property_address TEXT NULL

source_name TEXT
source_url TEXT NULL

matching_method TEXT
match_confidence NUMERIC

priority_category TEXT NULL
priority_score NUMERIC NULL

survival_probability NUMERIC NULL

requires_manual_review BOOLEAN DEFAULT FALSE

created_at TIMESTAMP
updated_at TIMESTAMP

--------------------------------------------------
8. LIEN TYPES
--------------------------------------------------

Support at minimum:

MORTGAGE
MORTGAGE_DISCHARGE
LIS_PENDENS
JUDGMENT
TAX_SALE_CERTIFICATE
PROPERTY_TAX
MUNICIPAL_LIEN
UCC
CONSTRUCTION_LIEN
HOMEOWNER_ASSOCIATION_LIEN
FEDERAL_TAX_LIEN
STATE_TAX_LIEN
OTHER

Do not assume every source supports every lien type.

--------------------------------------------------
9. OWNER TABLE
--------------------------------------------------

Create:

property_owners

Fields:

id
property_id
owner_name
normalized_owner_name
ownership_start
ownership_end
is_current_owner
mailing_address
source
confidence_score

Support multiple owners.

Example:

JOHN A SMITH
MARY B SMITH

Store individually rather than as one concatenated string whenever possible.

--------------------------------------------------
10. NAME NORMALIZATION
--------------------------------------------------

Create:

normalize_person_name()

Normalize:

"John A. Smith"
"JOHN SMITH"
"Smith, John A"
"John A Smith Jr."

into comparable structures.

Return:

{
 first_name,
 middle_name,
 last_name,
 suffix,
 normalized_full_name
}

Also support:

corporations
LLCs
trusts
estates

Example:

"ABC Property Holdings LLC"

should not be parsed as a person.

Create:

entity_type

PERSON
LLC
CORPORATION
TRUST
ESTATE
OTHER

--------------------------------------------------
11. LIEN MATCHING ENGINE
--------------------------------------------------

Create:

LienMatchingService

The system must avoid matching records based only on name.

Calculate match confidence using weighted signals.

Suggested features:

exact parcel match
exact PAMS PIN match
block/lot match
exact property address match
mailing address match
owner exact name match
owner fuzzy name match
county match
municipality match
recording timeframe
historical ownership timeframe

Example conceptual weighting:

PAMS PIN exact match:
+100 confidence evidence

Block + lot exact:
+90

Property address exact:
+85

Owner exact + address exact:
+80

Owner exact only:
+45

Owner fuzzy only:
+20

Common-name owner without property evidence:
very low confidence

Return:

match_confidence = 0-100

Suggested thresholds:

>= 85
HIGH confidence

65-84
MEDIUM confidence

<65
LOW confidence / manual review

Do not silently discard low-confidence records.

Instead flag them:

requires_manual_review = true

--------------------------------------------------
12. COMMON-NAME FALSE POSITIVES
--------------------------------------------------

This is especially important for statewide judgment searches.

Example:

Owner:
JOHN SMITH

A statewide judgment search may return hundreds or thousands of John Smith records.

Do NOT attach all results to the property.

Use:

property address
debtor mailing address
municipality
county
middle initial
co-defendant
historical owner addresses
recording dates

to calculate confidence.

If no secondary matching evidence exists:

do not classify the judgment as an active property lien.

Instead classify:

status = UNKNOWN
requires_manual_review = true

--------------------------------------------------
13. MORTGAGE RESOLUTION ENGINE
--------------------------------------------------

Create:

MortgageResolutionService

For each mortgage:

Search for potential:

DISCHARGE OF MORTGAGE
SATISFACTION OF MORTGAGE
RELEASE
ASSIGNMENT
MODIFICATION

Match discharge documents using:

instrument number
book/page
mortgagor
mortgagee
property parcel
recording references

Represent mortgage relationships.

Create table:

lien_relationships

Fields:

id
parent_lien_id
child_lien_id
relationship_type
confidence

relationship_type examples:

DISCHARGES
SATISFIES
ASSIGNS
MODIFIES
RELEASES
RELATED_TO

Example:

Mortgage 2017
       |
       +--- Discharge 2021

Mortgage status should become:

DISCHARGED

if the discharge match is high confidence.

--------------------------------------------------
14. FORECLOSURE / LIS PENDENS MATCHING
--------------------------------------------------

Create:

ForeclosureLinkingService

Sheriff sale records already contain information such as:

case_number
plaintiff
defendant
judgment_amount

Attempt to identify which mortgage/lien generated the foreclosure.

Match using:

case number
plaintiff
defendant
lis pendens
mortgagee
property
recording dates

Set:

is_foreclosing_lien = true

where confidence is sufficient.

This distinction is critical.

Do NOT treat the foreclosing mortgage as simply another unrelated lien.

--------------------------------------------------
15. LIEN PRIORITY ENGINE
--------------------------------------------------

Create:

LienPriorityService

Do NOT use a simplistic fixed assumption that every mortgage or judgment has equal risk.

Store:

priority_category

Suggested categories:

FORECLOSING_LIEN
SENIOR_LIEN
JUNIOR_LIEN
SUPER_PRIORITY_LIEN
POTENTIALLY_SURVIVING_LIEN
LIKELY_EXTINGUISHED_LIEN
UNKNOWN_PRIORITY

Calculate priority using factors such as:

recording date
lien type
foreclosure plaintiff
foreclosing mortgage
tax lien status
municipal claim
statutory priority
recorded subordination
sheriff sale case information

IMPORTANT:

The engine should produce:

estimated_priority

not a definitive legal conclusion.

Every priority conclusion must include:

priority_confidence

and

priority_reason

Example:

{
 "priority_category": "JUNIOR_LIEN",
 "priority_confidence": 82,
 "priority_reason":
   "Judgment recorded after foreclosing mortgage and debtor/property match is high confidence."
}

--------------------------------------------------
16. SURVIVAL ANALYSIS
--------------------------------------------------

Create:

LienSurvivalService

For each lien generate:

survival_classification

LIKELY_SURVIVES
MAY_SURVIVE
LIKELY_EXTINGUISHED
UNKNOWN

Also calculate:

survival_probability

0-100

This should be an analytical estimate only.

Consider:

lien type
priority
foreclosing lien
recording date
tax lien characteristics
municipal lien characteristics
federal/state status where identifiable
available foreclosure case information

Do not encode legal conclusions as absolute facts.

--------------------------------------------------
17. RISK ENGINE
--------------------------------------------------

Create:

LienRiskEngine

Do NOT simply add:

Lis Pendens = 40
Tax lien = 50
Mortgage = 30

Instead calculate risk using multiple dimensions.

Overall risk:

0-100

Calculate sub-scores:

data_quality_risk
title_complexity_risk
surviving_lien_risk
ownership_match_risk
tax_municipal_risk
judgment_risk
mortgage_priority_risk
manual_review_risk

Example output:

{
  "overall_score": 72,

  "risk_level": "HIGH",

  "components": {
      "surviving_lien_risk": 85,
      "title_complexity_risk": 60,
      "judgment_risk": 45,
      "tax_municipal_risk": 90,
      "data_quality_risk": 40
  }
}

Risk levels:

0-24
LOW

25-49
MODERATE

50-74
HIGH

75-100
VERY_HIGH

--------------------------------------------------
18. RISK FLAGS
--------------------------------------------------

Generate human-readable flags.

Examples:

"Open mortgage found with no matching discharge."

"Tax sale certificate identified."

"Possible judgment against owner requires manual verification."

"Multiple mortgages recorded."

"Foreclosing lien could not be confidently identified."

"Possible senior lien identified."

"Property owner name produces multiple statewide judgment matches."

"County records may not be current."

"No public lien records found. This does NOT confirm clean title."

"Manual county search required."

"Potential surviving lien identified."

Each flag should have:

severity

INFO
LOW
MEDIUM
HIGH
CRITICAL

category

message

source

confidence

related_lien_id

--------------------------------------------------
19. DATA FRESHNESS
--------------------------------------------------

Every source must store:

last_checked_at
source_last_updated_at
data_freshness_status

Possible statuses:

CURRENT
RECENT
STALE
UNKNOWN

Display this prominently.

Example:

County land records
Last checked:
August 11, 2026 2:14 PM

Source record freshness:
Unknown

Do not imply that absence of a record means the property is lien-free.

--------------------------------------------------
20. SCHEDULED INGESTION
--------------------------------------------------

Do not scrape every public source each time a user opens a property.

Create background jobs.

Preferred design:

initial historical import

then

incremental updates

Example:

County land-record collector

Daily process:

determine last successful record date

fetch newly recorded documents

normalize records

match records to tracked properties

update lien statuses

Recalculate risk score only when relevant data changes.

Create:

ingestion_jobs

Fields:

id
source
county
started_at
completed_at
status
records_found
records_inserted
records_updated
error_message

--------------------------------------------------
21. SOURCE RATE LIMITING
--------------------------------------------------

Implement polite request behavior.

Include:

rate limiting
request delays
retries
exponential backoff
user-agent identification where appropriate
caching

Do not repeatedly download identical records.

--------------------------------------------------
22. ERROR HANDLING
--------------------------------------------------

Each adapter must gracefully handle:

HTTP errors
timeouts
page structure changes
missing fields
CAPTCHA
rate limiting
unexpected formats

Return standardized errors.

Example:

{
 "status": "MANUAL_REVIEW_REQUIRED",
 "reason": "CAPTCHA detected",
 "source": "...",
 "recommended_action": "Open source website and search using owner name and block/lot."
}

One broken source must NOT prevent the entire property report from loading.

--------------------------------------------------
23. DATABASE SOURCE AUDITABILITY
--------------------------------------------------

Every normalized lien must preserve connection to the original source record.

User should be able to click:

"View Source"

and open the public source where legally/technically possible.

Never create a lien record without identifying its source.

--------------------------------------------------
24. FASTAPI ENDPOINTS
--------------------------------------------------

Create API endpoints.

GET
/api/v1/properties/{property_id}/liens

Return all normalized lien records.

GET
/api/v1/properties/{property_id}/lien-risk

Return:

overall score
risk level
component scores
risk flags
data freshness
manual review items

POST
/api/v1/properties/{property_id}/liens/refresh

Start refresh.

Do not make this endpoint block until every collector finishes.

Return:

{
 "job_id": "...",
 "status": "QUEUED"
}

GET
/api/v1/lien-jobs/{job_id}

Return job status.

GET
/api/v1/properties/{property_id}/ownership

Return current and historical ownership.

GET
/api/v1/properties/{property_id}/lien-sources

Return source status.

Example:

{
 "county_land_records": "SUCCESS",
 "judgments": "SUCCESS",
 "municipal_tax": "MANUAL_REVIEW_REQUIRED",
 "ucc": "SUCCESS"
}

--------------------------------------------------
25. RISK RESPONSE MODEL
--------------------------------------------------

Example API response:

{
  "property_id": "...",

  "overall_risk_score": 68,

  "risk_level": "HIGH",

  "summary":
  "Several recorded encumbrances were identified. One mortgage has no matched discharge and municipal tax status requires manual verification.",

  "liens": [
      {
          "type": "MORTGAGE",
          "amount": 325000,
          "recording_date": "2019-05-13",
          "status": "POSSIBLY_ACTIVE",
          "priority": "UNKNOWN_PRIORITY",
          "survival_classification": "UNKNOWN",
          "match_confidence": 97
      }
  ],

  "flags": [
      {
          "severity": "HIGH",
          "message":
          "Mortgage found with no matching discharge."
      }
  ],

  "manual_review": [
      {
          "source": "Municipal Tax Collector",
          "reason": "Automated access unavailable"
      }
  ],

  "last_updated": "..."
}

--------------------------------------------------
26. NEXT.JS USER INTERFACE
--------------------------------------------------

Add a new section to the existing property detail page.

Tab:

LIENS & TITLE RISK

At top display:

Lien Risk Score

Example:

68 / 100
HIGH RISK

Show:

Risk Summary

Example:

"Potential unresolved liens were identified. Review the highlighted records before bidding."

--------------------------------------------------
27. LIEN SUMMARY CARDS
--------------------------------------------------

Show cards for:

Open Mortgages
Judgments
Tax Liens
Lis Pendens
Municipal Liens
Other Liens

Example:

Open Mortgages
2

Tax Liens
1

Judgments
3 possible matches

Manual Review
2 items

--------------------------------------------------
28. LIEN TABLE
--------------------------------------------------

Columns:

Risk
Lien Type
Creditor
Debtor
Amount
Recorded
Status
Priority
Survival
Confidence
Source

Allow filters:

Active only

Likely survives

High risk

Manual review

Lien type

--------------------------------------------------
29. LIEN DETAIL DRAWER
--------------------------------------------------

Clicking a lien should open detailed information.

Display:

document type
creditor
debtor
amount
recording date
instrument number
book/page
case/docket number
property match explanation
status explanation
priority explanation
survival explanation
source
retrieval date
confidence score

Also show related documents.

Example:

MORTGAGE
   |
   +--- ASSIGNMENT
   |
   +--- DISCHARGE

--------------------------------------------------
30. RISK EXPLANATION
--------------------------------------------------

The user must be able to understand WHY a score exists.

Example:

Risk Score: 72

Contributing Factors:

Potential tax sale certificate
+ major risk

Unresolved mortgage
+ major risk

Possible statewide judgment
+ moderate risk

County records current
- lowers uncertainty

Never present only a number without explanations.

--------------------------------------------------
31. MANUAL REVIEW QUEUE
--------------------------------------------------

Create a section:

Manual Verification Required

Examples:

Municipal tax balance unavailable

Common-name judgment requires verification

County search blocked by CAPTCHA

Foreclosing mortgage could not be identified

For each item provide:

reason
source
recommended search terms
owner
property address
block
lot
case number if available

--------------------------------------------------
32. CONFIDENCE MODEL
--------------------------------------------------

Keep risk and confidence separate.

Example:

HIGH RISK
LOW CONFIDENCE

is possible.

A property may look risky because available data is incomplete.

Expose:

risk_score
risk_confidence

Example:

Risk Score: 75
Confidence: 43%

Display:

"High potential risk, but additional verification is required because several data sources were unavailable."

--------------------------------------------------
33. TESTING REQUIREMENTS
--------------------------------------------------

Create unit tests for:

name normalization
address normalization
PAMS PIN matching
block/lot matching
mortgage discharge matching
duplicate records
owner matching
common-name false positives
risk scoring
priority classification
manual-review fallback

Create integration tests for:

adapter -> raw record
raw record -> normalized lien
normalized lien -> property match
property liens -> risk report

Mock external public websites during automated tests.

Do not make production public-record requests in unit tests.

--------------------------------------------------
34. SAMPLE TEST CASE
--------------------------------------------------

Property:

123 SAMPLE ST
TOMS RIVER NJ

Owner:

JOHN A DOE

Records:

Mortgage
$400,000
recorded 2017

Mortgage discharge
recorded 2021
references 2017 mortgage

Mortgage
$250,000
recorded 2022

Lis Pendens
recorded 2025

Judgment
JOHN DOE
recorded 2018
different address

Expected:

2017 mortgage:
DISCHARGED

2022 mortgage:
POSSIBLY_ACTIVE

Lis Pendens:
ACTIVE

Judgment:
LOW CONFIDENCE
MANUAL REVIEW
should NOT automatically be attached as confirmed lien

Risk:
HIGH

Reasons:
active foreclosure activity
unresolved recent mortgage

--------------------------------------------------
35. PERFORMANCE
--------------------------------------------------

Property dashboard should load cached lien results immediately.

Do NOT wait for external source queries during normal page rendering.

Use:

database cached results

and separately show:

Last Updated

Refresh button:

"Refresh Lien Search"

--------------------------------------------------
36. SECURITY
--------------------------------------------------

Validate all API inputs.

Do not allow arbitrary URLs to be supplied to server-side fetch functions.

Prevent SSRF.

Store only public-record information necessary for property analysis.

Do not expose internal scraper credentials.

Use environment variables for configuration.

--------------------------------------------------
37. LOGGING
--------------------------------------------------

Log:

source requests
parser errors
record counts
matching decisions
risk recalculations

Do NOT log sensitive credentials.

Create structured application logs.

--------------------------------------------------
38. CODE ORGANIZATION
--------------------------------------------------

Suggested backend structure:

backend/
    app/
        api/
            liens.py
            lien_jobs.py

        models/
            lien.py
            owner.py
            raw_record.py

        schemas/
            lien.py
            risk.py
            ownership.py

        services/
            property_identity.py
            lien_matching.py
            lien_resolution.py
            lien_priority.py
            lien_survival.py
            lien_risk.py

        sources/
            base.py

            county/
                base.py
                monmouth.py
                ocean.py

            judgments/
                nj_judgments.py

            municipal/
                base.py

            ucc/
                nj_ucc.py

        jobs/
            lien_ingestion.py

        utils/
            address_normalization.py
            name_normalization.py
            hashing.py

--------------------------------------------------
39. FRONTEND STRUCTURE
--------------------------------------------------

Suggested:

components/
    liens/
        LienRiskCard.tsx
        LienSummaryCards.tsx
        LienTable.tsx
        LienDetailDrawer.tsx
        RiskFactors.tsx
        ManualReviewPanel.tsx
        SourceStatus.tsx

services/
    liens.ts

types/
    liens.ts

--------------------------------------------------
40. IMPLEMENTATION PHASES
--------------------------------------------------

Do NOT attempt every NJ county immediately.

Build incrementally.

PHASE 1

Database schema

Property identity resolver

Lien models

Risk model

Mock/sample lien data

API

Frontend

PHASE 2

One county land-record adapter

Mortgage/discharge matching

Lis pendens

PHASE 3

Statewide judgment adapter

Owner matching

Common-name filtering

PHASE 4

Municipal/tax records

Tax sale certificates

PHASE 5

Additional counties

PHASE 6

Advanced lien priority and survival logic

--------------------------------------------------
41. FIRST DEVELOPMENT TARGET
--------------------------------------------------

For the first implementation:

1. Create database migrations.

2. Create all SQLAlchemy/Pydantic models.

3. Create PropertyIdentityService.

4. Create normalization utilities.

5. Create abstract LienSourceAdapter.

6. Create mock/test source adapter.

7. Create LienMatchingService.

8. Create MortgageResolutionService.

9. Create LienRiskEngine.

10. Create FastAPI endpoints.

11. Add Lien & Title Risk tab to property page.

12. Populate with sample data.

13. Add unit tests.

Do NOT implement real scraping until the internal data pipeline works correctly.

--------------------------------------------------
42. CODING REQUIREMENTS
--------------------------------------------------

Use:

Python type hints

Pydantic schemas

async FastAPI endpoints

SQLAlchemy compatible with PostgreSQL/Supabase

clear service separation

dependency injection where practical

small reusable functions

pytest

TypeScript strict typing

React functional components

Avoid duplicated business logic.

Risk calculations should live exclusively in backend services.

--------------------------------------------------
43. IMPORTANT DESIGN PRINCIPLE
--------------------------------------------------

The system must distinguish these concepts:

RECORD EXISTS

vs

RECORD MATCHES THIS PERSON

vs

RECORD MATCHES THIS PROPERTY

vs

RECORD IS STILL ACTIVE

vs

RECORD HAS PRIORITY

vs

RECORD MAY SURVIVE THE SHERIFF SALE

These must never be treated as the same thing.

This distinction is one of the most important parts of the entire application.

--------------------------------------------------
44. FINAL PROPERTY OUTPUT
--------------------------------------------------

The user should ultimately see something similar to:

LIEN & TITLE RISK

Risk Score
72 / 100

HIGH

Confidence
81%

Potentially Active Liens
3

Likely Surviving Liens
1

Manual Reviews
2

Major Findings

• Tax sale certificate potentially outstanding.
• Mortgage recorded in 2021 has no matched discharge.
• One judgment may belong to the owner but requires address verification.
• Foreclosing mortgage identified with 92% confidence.

Data Sources

County Land Records
✓ Checked

NJ Judgments
✓ Checked

Municipal Tax
⚠ Manual verification required

UCC
✓ Checked

Last Updated:
August 11, 2026

DISCLAIMER

This automated analysis uses publicly available records and probabilistic matching. It is intended for preliminary investment screening and is not a certified title search or legal opinion. Verify title, lien priority, taxes, municipal charges, and surviving interests with qualified professionals before bidding.
