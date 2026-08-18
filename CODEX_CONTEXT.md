You are helping me continue development of an existing full-stack NJ sheriff-sale property analysis platform.

Please first inspect the repository structure and existing code before changing anything. Do not assume filenames, database models, API routes, or schemas are exactly as described below. The information below explains the intended architecture and project goals, but the repository is the source of truth.

PROJECT GOAL

I am building a platform that collects New Jersey sheriff-sale listings, starting with Monmouth County, enriches each property with real-estate valuation and public-record information, and helps investors evaluate potential opportunities.

The final product should function somewhat like a simplified PropStream-style sheriff-sale dashboard.

The platform should eventually allow a user to:

1. View all upcoming sheriff-sale properties.
2. Filter listings by county, municipality, ZIP code, sale date, status, upset price, market value, equity, and risk.
3. See the latest sale status, such as Scheduled, Adjourned, Cancelled, Sold, or Redeemed.
4. Review important foreclosure financial figures, especially:
   - Upset price
   - Judgment amount
   - Daily interest
   - Attorney fees and costs
   - Municipal liens or charges
   - Tax-sale certificates
   - Property taxes
   - Water and sewer charges
5. See an estimated market value.
6. Calculate estimated equity.
7. Show confidence, data-quality, and risk indicators.
8. Preserve historical status changes instead of only keeping the current status.
9. Eventually support additional New Jersey counties.
10. Eventually train a model to estimate the probability that a scheduled property actually proceeds to sale.

CURRENT TECHNOLOGY STACK

Frontend:
- Next.js
- TypeScript
- App Router
- Tailwind CSS
- Located under the frontend directory

Backend:
- Python
- FastAPI
- SQLAlchemy
- Located under the backend directory

Database:
- PostgreSQL hosted through Supabase

Deployment planned:
- Frontend on Vercel
- Backend on Railway or a similar platform
- Supabase for PostgreSQL

CURRENT PROJECT STATUS

The following functionality has already been developed or partially developed:

1. A Monmouth County CivilView scraper exists.
2. The scraper has successfully collected approximately 112 Monmouth County sheriff-sale records.
3. Approximately 46 records were identified as having the latest status Scheduled.
4. JSON output files have been generated, including files similar to:
   - monmouth_all_sheriff_sales.json
   - monmouth_scheduled_sheriff_sales.json
5. A FastAPI backend is running locally.
6. A Next.js frontend is running locally.
7. The frontend can currently display sheriff-sale data.
8. Supabase tables have already been created.
9. The sheriff_sales schema has recently been enhanced with additional fields.
10. The next major task is to extract detailed financial information from the listing description or detail pages.

IMPORTANT DATABASE FIELDS

The sheriff_sales table may already include some or all of these fields:

- id
- county
- sheriff_number
- docket_number
- current_status
- current_sale_date
- plaintiff
- defendant
- property_address
- city
- state
- postal_code
- judgment_amount
- upset_price
- estimated_upset_price
- alternate_upset_price
- daily_interest
- attorney_fees_costs
- deposit_percent
- balance_due_days
- owner_occupied
- description_text
- description_source_url
- description_parsed_at
- parser_version
- upset_price_conflict
- raw_payload
- created_at
- updated_at

Do not blindly recreate or alter these columns. Inspect the actual SQLAlchemy models, migrations, and database schema first.

There may also be or should eventually be tables similar to:

- properties
- sheriff_sales
- sheriff_sale_status_history
- sheriff_sale_charges
- property_valuations
- scrape_runs
- risk_assessments

CURRENT PRIMARY OBJECTIVE

The immediate goal is to populate Monmouth County sheriff-sale listings with at least:

1. Judgment amount
2. Upset price

We also want to parse and store any other useful structured values found in the listing description, notice text, or detail page.

Potential fields to extract include:

- Estimated upset amount
- Approximate upset amount
- Judgment amount
- Daily or per-diem interest
- Attorney fees
- Sheriff fees
- Municipal liens
- Property-tax amounts
- Tax-sale certificates
- Water charges
- Sewer charges
- Deposit percentage
- Balance-due period
- Owner-occupied status
- Vacant status
- Docket number
- Block
- Lot
- Qualifier
- Attorney name
- Attorney reference
- Property dimensions
- Nearest cross street
- Sale location
- Sale time

RAW DATA REQUIREMENT

Always preserve the original source material.

For each listing, save where available:

- Full raw description text
- Source URL
- Raw HTML when reasonable
- Date and time retrieved
- Parser version
- Original raw CivilView payload

The parser will improve over time, so old records must be reprocessable without downloading the pages again.

IMPORTANT PARSING PRINCIPLES

1. Do not treat every monetary amount as the upset price.
2. Classify values based on nearby labels and surrounding text.
3. Judgment amount and upset price are different values.
4. The opening bid is not necessarily the upset price.
5. A notice may contain more than one upset-price figure.
6. Preserve both estimated and approximate upset values when both appear.
7. Create a preferred upset price using a transparent hierarchy.
8. Flag conflicts when two upset-price values differ materially.
9. Do not overwrite a reliable existing database value with null.
10. Do not silently overwrite a manually corrected value with a lower-confidence parser result.

PREFERRED UPSET-PRICE LOGIC

Use a transparent hierarchy similar to:

preferred_upset_price =
    estimated_upset_price
    or alternate_upset_price
    or existing upset_price

If both estimated_upset_price and alternate_upset_price are present, calculate whether there is a material conflict.

A possible conflict rule is:

- Difference greater than $1,000
- And difference greater than 1% of the larger value

Store or expose the conflict flag instead of silently selecting one amount.

CURRENT PIPELINE DIRECTION

The intended pipeline is:

CivilView search results
→ open each CivilView detail page
→ identify any linked notice, embedded description, iframe, PDF, or secondary page
→ save the raw description
→ parse structured financial and property fields
→ upsert the listing into Supabase
→ retain status history
→ validate a sample manually
→ enrich with a valuation provider
→ calculate equity
→ show results in the frontend

FIRST DEVELOPMENT PHASE

Please focus first on the Monmouth County scraping and parsing pipeline.

Tasks:

1. Inspect the existing CivilView adapter and scraper.
2. Determine exactly where the detail-page URL is stored.
3. Inspect the actual Monmouth CivilView detail-page HTML.
4. Determine where judgment amount and upset price appear:
   - directly in HTML
   - inside description text
   - inside a table
   - inside an iframe
   - in a linked public notice
   - in a PDF
   - loaded dynamically through another request
5. Update the scraper to retrieve the correct source.
6. Extract and preserve the complete raw description.
7. Implement a reusable parser.
8. Populate judgment and upset-price fields.
9. Parse other useful financial amounts when present.
10. Upsert the results into PostgreSQL.
11. Produce a summary report showing:
    - total listings processed
    - detail pages downloaded
    - judgment amounts found
    - upset prices found
    - descriptions missing
    - parsing errors
    - records requiring manual review

Do not start by writing speculative regular expressions without inspecting at least one real saved Monmouth description.

PARSER DESIGN

Create or improve a parser module with clear separation between:

- HTTP retrieval
- HTML extraction
- Text normalization
- Field parsing
- Validation
- Database persistence

A reasonable structure may look like:

backend/
  pipeline/
    adapters/
      monmouth.py
    parsers/
      sale_description_parser.py
    services/
      sheriff_sale_persistence.py
    scripts/
      scrape_monmouth.py
      inspect_monmouth_record.py
      persist_monmouth_sales.py

Use the repository's existing structure when one already exists. Do not reorganize the whole project unnecessarily.

The parser should return a structured result, for example:

{
  "judgment_amount": 620450.25,
  "estimated_upset_price": 663061.99,
  "alternate_upset_price": null,
  "daily_interest": 54.30,
  "attorney_fees_costs": null,
  "docket_number": "F-012345-25",
  "block": "120",
  "lot": "14.02",
  "owner_occupied": true,
  "deposit_percent": 20,
  "balance_due_days": 30,
  "parser_version": "monmouth-description-v1",
  "upset_price_conflict": false,
  "manual_review_required": false,
  "parse_warnings": []
}

Use Decimal for monetary calculations in Python, not float.

DATABASE UPSERT REQUIREMENTS

The scraper will run repeatedly.

Upserts should:

1. Avoid duplicate sheriff-sale records.
2. Use a stable identity such as county plus sheriff_number.
3. Update changed current values.
4. Preserve prior status observations.
5. Preserve raw source text.
6. Avoid replacing non-null values with null.
7. Track updated_at.
8. Track parser_version.
9. Be safe to rerun.
10. Use transactions where appropriate.

If the database currently lacks a unique constraint for county plus sheriff_number, identify that clearly before attempting to rely on it.

STATUS HISTORY

The system should not lose earlier statuses.

A listing may move through:

Scheduled
→ Adjourned
→ Rescheduled
→ Cancelled
→ Sold
→ Redeemed

Inspect whether a status-history table already exists.

Each scrape should compare the observed status and sale date with the last known observation and append a new history record only when something meaningful changes.

VALIDATION REQUIREMENT

Before bulk persistence, validate at least five diverse listings when possible:

1. Standard residential property
2. Condominium
3. Multi-family or multi-property listing
4. Adjourned or rescheduled listing
5. Listing containing both judgment and upset values

Provide a small diagnostic command that prints:

- Sheriff number
- Address
- Source URL
- Raw matched text
- Parsed judgment amount
- Parsed upset amount
- Warnings
- Confidence or manual-review status

Do not proceed to RentCast until real Monmouth records show credible non-null judgment and upset-price values.

SECOND DEVELOPMENT PHASE: RENTCAST

After the sheriff financial fields are reliable, implement a valuation-provider abstraction.

The first provider should be RentCast, but the rest of the application should not depend directly on RentCast-specific response fields.

Create an interface similar to:

class ValuationProvider:
    def get_valuation(self, address: NormalizedAddress) -> ValuationResult:
        ...

Potential future providers may include:

- RentCast
- ATTOM
- Zillow-approved services
- County assessment data
- A custom comparable-sales model

Store provider-independent results in property_valuations.

Potential fields:

- id
- property_id
- provider
- provider_property_id
- estimated_value
- value_low
- value_high
- confidence_score
- subject_bedrooms
- subject_bathrooms
- subject_square_feet
- subject_property_type
- comparable_count
- raw_response
- valuation_date
- retrieved_at
- created_at
- updated_at

Do not hard-code API keys.

Use environment variables such as:

RENTCAST_API_KEY=

Never commit secrets.

RENTCAST TEST PLAN

1. Select one listing with a clean, normalized address.
2. Call RentCast for that single property.
3. Print a sanitized response.
4. Confirm the returned subject property matches the intended address.
5. Save the valuation in property_valuations.
6. Preserve the raw provider response.
7. Confirm rerunning the command does not create unintended duplicates.
8. Only after successful validation should bulk enrichment be considered.

ADDRESS NORMALIZATION

Before calling RentCast, classify addresses as:

- valid
- missing_street
- missing_city
- missing_zip
- multiple_properties
- needs_review

Do not spend API credits on clearly malformed or ambiguous addresses.

EQUITY CALCULATIONS

After valuation data exists, calculate:

preferred_upset_price =
    estimated_upset_price
    or alternate_upset_price
    or upset_price

gross_equity =
    estimated_market_value - preferred_upset_price

equity_percent =
    gross_equity / estimated_market_value * 100

Also calculate separately:

judgment_spread =
    estimated_market_value - judgment_amount

Do not call judgment_spread auction equity.

Use Decimal and handle null or zero values safely.

It may be better to calculate these fields in a service layer or API response rather than permanently storing every derived value. Inspect the current design before deciding.

FRONTEND GOAL

The frontend currently displays the sheriff-sale listings.

Eventually show columns such as:

- Address
- Municipality
- Sale date
- Status
- Judgment amount
- Estimated upset price
- Alternate upset price
- Preferred upset price
- Market value
- Value range
- Gross equity
- Equity percentage
- Data-quality score
- Manual-review flag
- Last updated

Useful filters:

- County
- Municipality
- ZIP code
- Sale date
- Status
- Minimum market value
- Maximum upset price
- Minimum equity
- Minimum equity percentage
- Valuation available
- Upset price available
- Manual review required

Do not redesign the entire frontend during the scraping phase. Add frontend changes only after the backend data is verified.

RISK-SCORING DIRECTION

Do not implement a misleading legal-risk score yet.

First create a data-quality score based on completeness and confidence.

Possible factors:

- Clean normalized address
- Judgment amount present
- Upset price present
- Source description saved
- Valuation available
- Address matched by valuation provider
- No upset-price conflict
- Parcel or block/lot available
- No multiple-property ambiguity

Later, risk may be separated into:

1. Data-quality risk
2. Sale-process risk
3. Recorded-lien risk
4. Potential surviving-lien risk
5. Overall investment risk

Any lien or title analysis must clearly state that it is preliminary screening and not a title search or legal opinion.

FUTURE MACHINE-LEARNING GOAL

Eventually, I want to estimate the probability that a scheduled property proceeds to sale.

Do not build this model yet.

We first need historical observations including:

- Scheduled
- Adjourned
- Cancelled
- Redeemed
- Sold to third party
- Sold to plaintiff

The system should collect clean status history now so a model can be trained later.

CODING EXPECTATIONS

1. Inspect before editing.
2. Explain what you found in the repository.
3. Make small, testable changes.
4. Do not replace large working files unnecessarily.
5. Preserve current working functionality.
6. Add type hints.
7. Use clear names.
8. Add error handling.
9. Add logging instead of excessive print statements where appropriate.
10. Keep scripts runnable from the backend root.
11. Use environment variables for configuration.
12. Do not expose credentials.
13. Do not fabricate data.
14. Do not silently swallow exceptions.
15. Clearly identify any assumptions.
16. Add tests for parsing logic.
17. Add diagnostic output for scraper failures.
18. Avoid unnecessary dependencies.
19. Keep the design extensible to other NJ counties.
20. Show me commands to run and what successful output should look like.

WORKING STYLE

Before making changes, please:

1. Print the relevant repository tree.
2. Identify the existing scraper entry point.
3. Identify the Monmouth adapter.
4. Identify the database models and session setup.
5. Identify the current JSON record shape.
6. Identify the current frontend API contract.
7. Summarize the safest implementation plan.

Then begin with the smallest useful task:

Inspect one real Monmouth CivilView record and determine exactly where the upset price and judgment amount are located.

Do not proceed to broad refactoring until that has been confirmed.