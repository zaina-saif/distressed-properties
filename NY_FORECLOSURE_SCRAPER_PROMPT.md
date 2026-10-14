Build an Automated NY Foreclosure Data Pipeline for SheriffSaleHunter.ai

You are an expert web scraping, browser automation, and data extraction engineer working on SheriffSaleHunter.ai, a foreclosure and sheriff sale investment intelligence platform.

Your task is to build, test, and execute a resilient production-ready pipeline that collects New York foreclosure auction calendars, case histories, and mortgage debt information from official New York State court systems.

Do not stop at writing a design document or pseudocode. Inspect the available tools, implement the actual code, test it against real court records, validate the extracted data, and report the results.

1. Objective

Build a repeatable automated pipeline targeting:

New York WebCivil Supreme

https://iapps.courts.state.ny.us/webcivil/FCASCalendarSearch

NYSCEF — New York State Courts Electronic Filing

https://iapps.courts.state.ny.us/nyscef/

The pipeline must:

Find foreclosure auction calendars for 11 New York counties.

Extract all foreclosure auction case records.

Open individual case details.

Extract court appearance histories and auction statuses.

Follow NYSCEF document links.

Identify original mortgage debt and property information from filed documents.

Normalize and save the collected information.

Support scheduled incremental updates for SheriffSaleHunter.ai.

Prioritize verified data from official court sources. Never invent missing values.

2. Existing Bright Data MCP Integration

IMPORTANT: Bright Data is already configured as an MCP server in Claude Code.

Use the existing Bright Data MCP integration as the primary scraping and browser automation provider.

Do not initially create a separate Bright Data WebSocket connection, install another proxy provider, or build a redundant browser integration.

Required steps

Discover all available Bright Data MCP tools.

Confirm the Bright Data MCP server is connected and functional.

Identify which tools support browser navigation, JavaScript-rendered pages, form interaction, page extraction, and PDF retrieval.

Use the appropriate available tools for WebCivil and NYSCEF.

Prefer Bright Data MCP for initial exploration and data extraction.

Reuse browser sessions when the available integration supports them.

Minimize unnecessary page navigation, repeated requests, and PDF downloads.

If MCP cannot perform an essential interaction, document the limitation and evaluate Bright Data Scraping Browser with Playwright/CDP as a fallback.

Do not assume MCP tool names. Discover their actual names and supported parameters.

Bright Data may provide managed browser functionality for website challenges. Use documented capabilities where permitted by the target website and applicable access restrictions. Do not implement custom CAPTCHA circumvention, clearance-cookie extraction, or security-control bypasses.

If a page remains inaccessible, record the restriction, skip that operation, and continue processing accessible records.

Important architectural requirement

Claude Code's MCP tools are not automatically callable from a standalone Node.js script.

Investigate how the pipeline can invoke Bright Data programmatically at runtime.

Choose one of these approaches based on actual capabilities:

Bright Data MCP via an appropriate programmatic MCP client.

Bright Data Scraping Browser using Playwright/CDP, if needed for complex browser interactions.

A hybrid implementation in which MCP handles supported extraction and Playwright handles interactions unsupported by MCP.

Use the minimum necessary infrastructure and avoid duplicating functionality.

The finished pipeline must execute independently of an interactive Claude Code conversation.

3. Target Counties

Process each county independently.

New York (Manhattan)

Kings (Brooklyn)

Queens

Bronx

Richmond (Staten Island)

Nassau

Suffolk

Westchester

Orange

Onondaga

Erie

Start with Queens County only.

Do not process the remaining counties until Queens extraction and validation have succeeded.

Account for differences in court-part names, available calendars, and foreclosure procedures between counties.

4. Step 1 — Navigate to WebCivil Supreme

Target:

https://iapps.courts.state.ny.us/webcivil/FCASCalendarSearch

Using Bright Data:

Open the WebCivil Supreme portal.

Inspect the actual page structure.

Identify the court/county dropdown.

Select the target county.

Identify the "Court Part" or "Select a Court Part" dropdown.

Inspect all available court-part options.

Select the part associated with foreclosure auctions.

Submit the search.

Wait for the results table to load.

Extract available calendar results.

Potential foreclosure part names include:

FORECLOSURE AUCTION PART

FRP

MASTER FORECLOSURE PART

AUCTION PART

Foreclosure Auction

Do not assume these names are present or that every county uses identical naming conventions.

Inspect the actual dropdown values.

If a county lacks an identifiable foreclosure auction part:

Record all available part names.

Mark the county as requiring mapping review.

Do not arbitrarily choose an unrelated court part.

Continue to the next county.

Do not hardcode selectors before inspecting the live DOM.

5. Step 2 — Extract Foreclosure Calendar Records

For each calendar result, extract:

County

Court name

Court part

Index number

Case caption

Plaintiff

Defendant

Scheduled auction date

Scheduled auction time

Appearance purpose

Current calendar outcome

Plaintiff attorney

Defendant attorney

Case detail URL, when available

Source URL

Extraction timestamp

Possible outcomes include:

Scheduled

Adjourned

Not Held

Cancelled

Completed

Unknown

Preserve the original status text alongside any normalized status.

Pre-filtering

If a row explicitly indicates:

Not Held

Cancelled

Record the original row and status.

Skip expensive document enrichment for those rows during the initial run unless they are needed to establish sale-history changes.

Do not discard cancelled or adjourned records. They may provide valuable historical features for foreclosure auction probability modeling.

Pagination

Determine whether the results span multiple pages.

If pagination exists:

Traverse all available results pages.

Avoid duplicate records.

Track page counts.

Record the number of cases retrieved.

Stop only after reaching the end of the result set or encountering a documented access limit.

6. Step 3 — Open Individual Case Details

For each eligible foreclosure case:

Open the case detail link.

Preserve the existing browser session when supported.

Wait for the case information to load.

Extract all available case metadata.

Required fields:

Index number

Case caption

Court

Court part

Assigned justice

Case status

Filing date

Property address, if displayed

Assigned foreclosure referee, if displayed

Plaintiff attorney

Defendant attorney

Source URL

Do not infer a referee or property address when the court page does not explicitly provide one.

7. Step 4 — Extract Complete Appearance History

Locate:

Show Appearances

Appearances

Case Appearances

Use the actual interface labels found on the page.

Open the appearance-history section.

Extract every available historical row:

Appearance date

Court part

Presiding justice

Appearance purpose

Outcome

Decision

Adjournment information, if displayed

Original source text

Examples of appearance purposes:

Motion

Conference

Judgment of Foreclosure

Foreclosure Auction

Sale Hearing

Examples of outcomes:

Granted

Denied

Adjourned

Not Held

Completed

Preserve the historical sequence.

Do not overwrite historical appearances with only the most recent status.

This information is important for SheriffSaleHunter.ai's prediction models.

8. Step 5 — Navigate to NYSCEF

On the case details page, locate:

Show eFiled Documents

This may open NYSCEF in a separate browser tab or window.

Support:

Same-tab navigation

New-tab navigation

JavaScript-generated navigation

Direct docket links when available

Maintain the correct case association.

If implementing this with Playwright, use appropriate new-page event handling rather than assuming every link opens in the same tab.

If the case does not have accessible e-filed documents, record:

{
  "nyscef_accessible": false,
  "efiled_documents_summary": null
}

Do not fabricate NYSCEF information.

9. Step 6 — Find Mortgage and Foreclosure Documents

Inspect the NYSCEF document list.

Prioritize documents labeled:

SUMMONS WITH NOTICE

SUMMONS AND COMPLAINT

COMPLAINT

NOTICE OF PENDENCY

AMENDED COMPLAINT

JUDGMENT OF FORECLOSURE AND SALE

REFEREE REPORT OF AMOUNT DUE

Capture:

Document number

Document type

Filing date

Document title

Available document URL

Whether a PDF is accessible

Document extraction priority

First: Use structured HTML document metadata when it contains the required values.

Second: Use document text previews if available.

Third: Download and parse PDFs when necessary and permitted.

Avoid unnecessary downloads of large PDFs.

For text-based PDFs, use a reliable PDF text extraction library.

For scanned PDFs, use OCR only when required, and record reduced confidence where appropriate.

10. Step 7 — Extract Debt and Property Information

From the relevant filed documents, extract the following information whenever explicitly available.

Mortgage and debt

Original lender or mortgagee

Current plaintiff or assignee

Original mortgage principal

Unpaid principal balance

Amount claimed due

Judgment amount

Mortgage recording date

Default date

Interest rate, if stated

Important: These are separate financial values.

Do not assume the original mortgage amount equals the current amount due.

Do not assume the amount claimed in an initiating complaint equals the final judgment amount.

Maintain source-document references for every extracted financial value.

Property information

Street address

City

State

ZIP code

County

Borough

Block

Lot

Section, when applicable

Full tax parcel identifier

Legal property description, when available

For New York City properties, support Borough-Block-Lot identifiers.

For counties outside New York City, preserve the jurisdiction's actual tax parcel identification format.

Data extraction requirements

Extract values directly supported by court records.

Preserve exact currency figures.

Distinguish principal balance from other claimed amounts.

Normalize addresses.

Preserve raw source text for auditability.

Associate each value with its supporting document number and filing date.

Return null where evidence is insufficient.

For example:

{
  "unpaid_principal_balance": 450000.00,
  "balance_source": {
    "document_type": "SUMMONS AND COMPLAINT",
    "document_number": 1,
    "filing_date": "2021-04-12",
    "page_number": 8
  }
}

Never invent a debt amount to satisfy the schema.

11. Step 8 — Normalize Data into JSON

Save each county's output to:

./data/ny_foreclosures/<county_name>_<date>.json

Use this target structure:

{
  "county": "Queens",
  "index_number": "713725/2021",
  "court": "Queens Supreme Court",
  "court_part": "FORECLOSURE AUCTION PART",
  "scheduled_auction_date": "2026-10-16",
  "scheduled_auction_time": null,
  "status": "Scheduled",
  "raw_status": "Scheduled",
  "plaintiff": "US BANK NATIONAL ASSOCIATION",
  "defendant": "TELLO, JONNI R. ETAL",
  "property_details": {
    "address": "123 Main St",
    "city": "Queens",
    "state": "NY",
    "zip": null,
    "borough_block_lot": "4-01234-0056",
    "tax_parcel_id": null,
    "original_mortgage_amount": null,
    "unpaid_principal_balance": 450000.00,
    "amount_claimed_due": null,
    "judgment_amount": null
  },
  "referee_name": "John Doe, Esq.",
  "plaintiff_attorney": "DRUCKMAN LAW GROUP PLLC",
  "defendant_attorney": null,
  "appearance_history": [
    {
      "date": "2026-08-10",
      "part": "MFJ",
      "purpose": "Motion",
      "outcome": "Granted",
      "justice": null
    }
  ],
  "efiled_documents_summary": {
    "nyscef_accessible": true,
    "initiating_doc": "SUMMONS WITH NOTICE",
    "filing_date": "2021-04-12",
    "document_number": 1
  },
  "source_metadata": {
    "calendar_url": null,
    "case_detail_url": null,
    "nyscef_url": null,
    "extracted_at": null
  }
}

The example is illustrative only. Do not treat any example names, dates, case numbers, amounts, or statuses as verified court records.

Validation rules

Preserve index numbers as strings.

Parse dates into ISO 8601 format.

Store numeric amounts without currency symbols.

Use null for missing values.

Preserve raw values alongside normalized values where useful.

Check for duplicate records.

Allow multiple historical auction events for the same case.

Track when a record was last updated.

12. Step 9 — Error Handling and Rate Limiting

Build resilient error handling around every major extraction stage.

Handle:

Browser connection errors

Navigation timeouts

Missing dropdowns

Dynamic content changes

Empty results

Session expiration

NYSCEF redirection failures

PDF retrieval errors

Access restrictions

Rate limits

Malformed documents

Use configurable 30-second navigation timeouts as the initial default.

Use conservative request pacing, starting at approximately 1,500 ms between case requests, and increase delays when required.

Do not assume that a fixed delay guarantees compliance with site limits.

Use exponential backoff for transient errors, but do not repeatedly retry pages that are explicitly blocked by an access restriction.

Checkpointing

After every successfully processed case:

Save the record.

Update the processing checkpoint.

Record the current county and index number.

Avoid restarting the entire county after one failure.

Support resuming interrupted jobs.

Structured failure reporting

Example:

{
  "county": "Queens",
  "index_number": "713725/2021",
  "stage": "nyscef_document_retrieval",
  "error_type": "access_challenge",
  "status": "manual_review_required",
  "retry_count": 1
}

Do not discard previously collected records when an enrichment step fails.

13. Step 10 — Bright Data Bandwidth Optimization

Bright Data usage should be cost-conscious.

Implement the following optimizations where supported:

Avoid unnecessary images, fonts, and media.

Preserve scripts required for interactive navigation.

Reuse sessions.

Prefer HTML metadata over PDF downloads.

Avoid downloading the same document twice.

Cache document metadata.

Deduplicate requests.

Use incremental updates after the initial complete run.

If using a compatible Playwright routing implementation:

await page.route(
  '**/*.{png,jpg,jpeg,svg,woff,woff2,gif}',
  route => route.abort()
);

Verify that route interception is supported by the actual Bright Data browser connection and does not break the court website.

Do not assume a specific bandwidth reduction or fixed cost per case without measuring actual traffic.

Provide estimated usage statistics after testing.

14. Step 11 — Production Architecture

Implement an organized Node.js project.

Suggested structure:

ny-foreclosure-scraper/
├── package.json
├── .env.example
├── .gitignore
├── README.md
├── scrape_ny_courts.js
├── src/
│   ├── browser/
│   │   └── brightDataClient.js
│   ├── extractors/
│   │   ├── calendarExtractor.js
│   │   ├── caseExtractor.js
│   │   ├── appearancesExtractor.js
│   │   ├── nyscefExtractor.js
│   │   └── pdfExtractor.js
│   ├── utils/
│   │   ├── normalize.js
│   │   ├── checkpoint.js
│   │   ├── rateLimiter.js
│   │   └── logger.js
│   └── config/
│       └── counties.js
├── data/
│   └── ny_foreclosures/
├── logs/
└── tests/

Adjust the architecture if the available Bright Data MCP integration requires a different implementation.

Dependencies

Install dependencies according to the selected implementation.

For example:

npm init -y
npm install playwright dotenv

If direct MCP integration is used, install the appropriate official MCP client dependencies.

Only install dependencies actually required.

Configuration

Use environment variables for:

Bright Data credentials and configuration

Request delays

Navigation timeouts

Output directory

Target counties

Logging level

Maximum retries

Never commit API keys or credentials.

15. Step 12 — Queens County Test

Before running all 11 counties, complete an end-to-end test against Queens.

Test sequence

Connect to Bright Data.

Open WebCivil Supreme.

Select Queens County.

Identify the foreclosure auction part.

Submit the calendar search.

Extract the available calendar records.

Choose one accessible active foreclosure case.

Open the case details.

Extract its appearance history.

Open its NYSCEF docket, if available.

Locate its initiating complaint or summons.

Extract available property and debt information.

Normalize the result.

Save the JSON record.

Verify the extracted information against the actual source pages or documents.

Test acceptance criteria

Confirm:

Calendar extraction works.

Index numbers are accurate.

Auction dates are parsed correctly.

Case details match the correct index number.

Appearance histories remain associated with the correct case.

NYSCEF docket links resolve to the intended case.

Debt values are supported by source documents.

Missing values are represented as null.

Output JSON passes schema validation.

The pipeline can recover from individual record failures.

Provide the location of the generated Queens JSON file.

If testing fails, investigate and fix the implementation before proceeding.

Do not report a successful test without actual execution and verification.

16. Step 13 — Expand to Remaining Counties

After Queens passes validation, process:

New York

Kings

Bronx

Richmond

Nassau

Suffolk

Westchester

Orange

Onondaga

Erie

Execute counties sequentially initially to control load and simplify debugging.

For each county, record:

Calendar availability

Foreclosure part used

Total records found

Records successfully extracted

Records enriched from NYSCEF

Records missing debt information

Cancelled or adjourned records

Extraction failures

Access restrictions

Execution duration

Allow counties with unavailable calendars to be skipped without stopping the complete pipeline.

17. Step 14 — Incremental Updates and Historical Tracking

SheriffSaleHunter.ai requires both current foreclosure auction listings and historical status changes.

Do not simply replace old records with new ones.

Implement an incremental update strategy that:

Identifies cases by county and index number, with court and other identifiers as needed.

Detects new cases.

Detects new auction dates.

Detects adjournments.

Detects cancellations.

Detects completed auctions when officially reported.

Preserves historical appearance records.

Avoids duplicate auction events.

Records when each observation was collected.

Supports exporting historical datasets for machine learning.

Where the same case receives a new auction date, preserve the previous scheduled date rather than overwriting it.

Use source-reported outcomes instead of assuming that a past scheduled auction was completed.

Make the pipeline suitable for future integration with SheriffSaleHunter.ai's existing backend and database.

18. Step 15 — Logging, Reporting, and Documentation

Create a README describing:

Architecture

Bright Data integration

Required environment variables

Installation

Local execution

Queens testing

Multi-county execution

Resume behavior

JSON schema

Troubleshooting

Operational limitations

At the end of execution, provide a summary similar to:

NY FORECLOSURE EXTRACTION REPORT

Counties requested: 11
Counties completed: <actual>
Total calendar cases: <actual>
Active auction cases: <actual>
Adjourned cases: <actual>
Cancelled cases: <actual>
Cases enriched from NYSCEF: <actual>
Cases with verified debt information: <actual>
Cases missing debt information: <actual>
Failed cases: <actual>
Execution time: <actual>
Estimated Bright Data usage: <measured or unavailable>

Use actual execution results, not invented metrics.

19. Final Deliverables

Produce:

Working scrape_ny_courts.js entry point.

Reusable extraction modules.

Bright Data MCP or browser integration.

Court calendar extraction.

Case detail and appearance-history extraction.

NYSCEF docket and document extraction.

Mortgage debt and property information parsing.

Normalized JSON output.

Checkpointing and error recovery.

Tests and sample validated output.

Documentation for rerunning the pipeline.

Execution report for all counties actually processed.

20. Execution Instructions — Start Now

Do not respond with only a plan. Begin implementing and testing the pipeline.

Proceed in this order:

Inspect the existing repository and available Bright Data MCP tools.

Confirm how Bright Data will be invoked by the production script.

Inspect WebCivil Supreme using Bright Data.

Implement the Queens workflow.

Execute the Queens test.

Validate the extracted data.

Fix any issues identified.

Expand to the remaining counties.

Save the resulting datasets.

Provide a final execution and validation report.

Use the existing repository's conventions, architecture, and environment where practical.

Avoid replacing functional components without a clear reason.

If a specific extraction step cannot be completed, explain the precise obstacle, preserve all successful work, and continue with independent accessible tasks.

Success means working, tested code and verifiable foreclosure data, not merely a proposed implementation.   