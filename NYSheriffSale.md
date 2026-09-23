1. The Core Data Engineering Strategy
To build this system, you cannot rely on a single public API because one does not exist. You will need to write separate workers for each of these pipelines:

[Your System Intake]
   ├── Pipeline A: Web Scraper -> NYC DOF Central Calendar (Dates/Locations)
   ├── Pipeline B: OCR / Text Parser -> Legal Notices (Addresses/Index Numb.)
   ├── Pipeline C: NYSCEF Web Services / Scrapers -> Court Case Verification
   └── Pipeline D: ACRIS API / OData -> Historical & Completed Deed Tracking
2. The Four Mandatory Pipelines to Build

🛠️ Pipeline A: The NYC Department of Finance (DOF) Auction Schedule
	•	Target: The NYC DOF Property Auctions Page (https://www.nyc.gov/site/finance/vehicles/auctions.page).
	•	What you get: The baseline schedule. It will tell your database when and in which borough a real property or personal property auction is happening.
	•	Ingestion Method: Build a basic Python web scra

Pipeline B: The Newspaper Legal Notice Scraping (The Hardest Part)
Because New York Civil Practice Law and Rules (CPLR § 5236) legally mandates that execution details be printed in local papers rather than online, this is where your database gets its unique value. [1 (https://law.justia.com/codes/new-york/cvp/article-52/5236/), 2 (https://www.thelangelfirm.com/debt-collection-defense-blog/2015/december/sale-of-real-property-through-sheriff-levy-new-y/)]
	•	Target Publications: The New York Law Journal, The City Record, and regional weeklies (like the Queens Chronicle or Brooklyn Eagle).
	•	Ingestion Method:
	1	API/Feeds: The City Record has a digital portal and search tool. You can build a scraper targeting keyword combinations like "Notice of Sale", "Sheriff's Sale", "Property Execution", or "At Public Auction".
	2	OCR Text Extraction: For hyper-local papers that only publish PDFs or print, you will need a document pipeline. Feed the legal notice sections through an Optical Character Recognition (OCR) engine like Tesseract or AWS Textract.
	3	Regex Extraction: Write Regular Expressions (Regex) to extract the critical data entities from the wall of text:
	▪	Index Number / Docket Number (e.g., Index No. 123456/2025)
	▪	BBL (Borough, Block, Lot) or Property Address
	▪	Debtor and Creditor names
	▪	Execution Amount / Judgment Total

⚖️ Pipeline C: NYSCEF Case Verification & Enrichment
Once your system extracts an Index Number from a legal notice, you must enrich that database entry by checking the underlying court record to ensure the sale is active and see what liens exist. [1 (https://www.thelangelfirm.com/debt-collection-defense-blog/2015/december/sale-of-real-property-through-sheriff-levy-new-y/)]
	•	Target: The New York State Courts Electronic Filing system (NYSCEF).
	•	Ingestion Method: While the public portal requires a login, legal tech tools like the Trellis Court Data API or custom browser automation tools can pull the active docket. [1 (https://support.trellis.law/trellis-api)]
	•	What to look for: Look for a "Writ of Execution" or a "Motion to Stay." If a debtor files for Chapter 13 bankruptcy or secures a court stay, the Sheriff sale is legally frozen. Your listing system needs to flag these as "Postponed" or "Stayed" so your users don’t show up to canceled auctions.

🏛️ Pipeline D: Post-Sale Records & Historical Tracking


To show your users historical sale data or completed transactions, you need access to the property land registries.
	•	Target (4 Boroughs): The NYC ACRIS System (https://www.nyc.gov/site/finance/property/acris.page). Unlike the front-end auction side, ACRIS actually has robust digital infrastructure. You can query its data via the NYC OpenData Portal API or hit the ACRIS database directly via OData protocols.
	•	Target (Staten Island): The Richmond County Clerk Property System.
	•	What to filter for: Query for Document Type: "DEED, SHERIFF" or "DEED, MARSHAL". This will populate your database with the exact historical clearing prices of completed executions. [1 (https://www.nyc.gov/site/finance/about/open-portal.page)]

NYC does have auctions with multiple properties—but the lists you’re looking for are generally called “foreclosure auction calendars.” These sales are handled through each county’s Supreme Court, with court-appointed referees conducting the auctions. My earlier answers focused too narrowly on sales conducted by the Sheriff.
There are two different processes:
Sale type	What it covers	Where to look
Foreclosure auction	Property sold under a foreclosure judgment	County Supreme Court auction calendars and published notices of sale
Sheriff’s execution sale	A debtor’s property interest sold to satisfy an unpaid money judgment	NYC Sheriff/Department of Finance notices and newspaper legal notices


The distinction is reflected in the court’s foreclosure rules and NYC’s sheriff sale description.
For the lists of properties, start here:
- Brooklyn: Kings County foreclosure sales. Click “LIST OF PROPERTIES.” The court currently lists September 17, 2026 as its next auction date.
- Queens: Queens foreclosure auctions. Follow its WebCivil eCourts calendar link. Its rules allow up to 60 properties per scheduled Friday, split into two sessions; that is capacity, not the actual number each week.
- Bronx: Bronx foreclosure page. Select “Pending Foreclosure Auctions.”
- Manhattan: The court publishes multi-case calendars—here’s an example for September 15, 2026, now past.
- Staten Island: Richmond County foreclosure auction information, including the auction department contact and schedule.
For your search, use the court calendar to find the batch of properties, then read each property’s Notice of Sale for details. A scheduled property can be withdrawn or stayed before bidding, as the Brooklyn court explicitly notes.i
