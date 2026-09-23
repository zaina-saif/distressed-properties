# Florida public property sources

Reviewed September 21, 2026.

This directory identifies official sources and agency-designated vendors for foreclosure auctions, tax deed auctions, unsold tax land, sheriff execution sales, government-owned real estate and earlier distress signals. Federal sources are labeled separately.

**Coverage:** a prioritized source directory, not a completed audit of every Florida county or municipality.

**Verification:** public pages and referral links were checked. Live collection was completed September 21 for Columbia foreclosures, Palm Beach sheriff sales, FDOT surplus property, SWFWMD land offers, and U.S. Treasury Florida real property. Other sources remain implementation assessments, not completed feeds.

**Start here:** Columbia foreclosure HTML, Palm Beach sheriff HTML, FDOT public search, SWFWMD HTML, and Treasury Florida real estate have initial collection routes. Then add the county RealForeclose/RealTaxDeed calendars and unsold-tax-land searches.

P1 = implement first; P2 = expand; P3 = monitor/discovery only.

## Foreclosure auctions

| Source | Public listing/data | Collection route and review notes | Priority |
|---|---|---|---|
| Columbia County Clerk — Columbia County | [Open source](https://columbiaclerk.com/clerk-services/foreclosures/upcoming-foreclosure-sales/) · [Official evidence](https://columbiaclerk.com/clerk-services/foreclosures/upcoming-foreclosure-sales/) | Public HTML listing; parse repeated labeled records. Actual future sale records were readable. Fields: status, sale date, case number, judgment amount, parties, address and parcel ID. Page revised September 10, 2026. Auctions themselves are in person; online bidding is not necessary for online listing collection. | P1 |
| Miami-Dade Clerk — Miami-Dade County | [Open source](https://www.miamidade.realforeclose.com/) · [Official evidence](https://www.miamidadeclerk.gov/clerk/mortgage-foreclosures.page) | Officially linked RealForeclose calendar; browser/session validation needed. Clerk page read and vendor link verified. Vendor did not return usable content through the research fetcher. Registration to bid is documented; listing automation remains untested. | P1 |
| Broward Clerk — Broward County | [Open source](https://www.broward.realforeclose.com/) · [Official evidence](https://www.browardclerk.org/Divisions/CircuitCivil) | Officially linked RealForeclose portal; browser/session validation needed. Clerk identifies this as its foreclosure sale site. Do not infer tax deed coverage from this foreclosure portal. | P1 |
| Palm Beach Clerk — Palm Beach County | [Open source](https://palmbeach.realforeclose.com/) · [Official evidence](https://www.mypalmbeachclerk.com/departments/courts/foreclosures) | Official auction calendar; browser/session validation needed. Official clerk search results and indexed Judicial Sales Procedure 21-02 identify the calendar. Direct clerk page fetch failed in this research tool. Sale dates and cancellations must be rechecked against the case file. | P1 |
| Hillsborough Clerk — Hillsborough County | [Open source](https://www.hillsborough.realforeclose.com/) · [Official evidence](https://www.hillsclerk.com/court-services/foreclosure-sales) | Officially linked RealForeclose calendar; browser/session validation needed. Clerk documents pending-sale information including owner, legal description and opening bid. Vendor fetch failed in research tool; this does not establish that ordinary browsing is blocked. | P1 |
| Duval Clerk — Duval County | [Open source](https://www.duval.realforeclose.com/) · [Official evidence](https://www.duvalclerk.gov/departments/civil-court-services/foreclosure) | Officially linked RealForeclose calendar, with CORE case lookup for enrichment. Official clerk page read; vendor fetch failed in research tool. Foreclosures can concern mortgages or other liens; retain case type. | P1 |
| Orange County Clerk — Orange County | [Open source](https://www.myorangeclerk.realforeclose.com/) · [Official evidence](https://www.myorangeclerk.com/Divisions/Civil/Foreclosures) | Officially linked RealForeclose portal; browser/session validation needed. Verified clerk link uses myorangeclerk.realforeclose.com. Vendor listing fetch failed in the research tool. | P1 |

## Tax deed auctions and unsold tax land

| Source | Public listing/data | Collection route and review notes | Priority |
|---|---|---|---|
| Orange County Comptroller — Orange County | [Open source](https://orange.realtaxdeed.com/) · [Official evidence](https://www.occompt.com/191/Tax-Deed-Sales) | Officially linked RealTaxDeed calendar; inspect listing session before automation. Comptroller confirms online tax deed auctions and separate research files. Vendor fetch failed in research tool. | P1 |
| Orange County Comptroller — Orange County | [Open source](https://or.occompt.com/recorder/tdsmweb/applicationSearch.jsp) · [Official evidence](https://www.occompt.com/191/Tax-Deed-Sales) | Public tax deed search; select Lands Available status. Also has an official ArcGIS map. Properties offered but not purchased at tax deed sale. Entry redirected to disclaimer/login.jsp; no successful results query was performed. Map: https://ocfl.maps.arcgis.com/apps/webappviewer/index.html?id=1436e42429f54bf88fde326e5aba9552 | P1 |
| Hillsborough Clerk — Hillsborough County | [Open source](https://hillsborough.realtaxdeed.com/) · [Official evidence](https://www.hillsclerk.com/pt/taxdeeds) | Officially linked RealTaxDeed calendar and separate clerk case documents. Clerk describes scheduled sales and redeemed statuses; bidder registration is separate from the collection question. Public case files include tax collector certification and ownership/encumbrance reports. | P1 |
| Hillsborough Clerk — Hillsborough County | [Open source](https://publicaccess.hillsclerk.com/TD/) · [Official evidence](https://www.hillsclerk.com/pt/taxdeeds) | Clerk Public Access View application; browser/form testing needed. Public Lands Available search entry was readable; full results were not collected. Clerk links it for the current tax deed and lands available lists. | P1 |
| Miami-Dade Clerk — Miami-Dade County | [Open source](https://www.miamidade.realforeclose.com/) · [Official evidence](https://www.miamidadeclerk.gov/clerk/property-tax-deeds.page) | Official combined foreclosure/tax deed vendor site; distinguish sale category. The tax deed page explicitly links the same RealForeclose hostname as foreclosures. Validate sale-type filters; do not infer a separate hostname. | P1 |
| Miami-Dade Clerk / tax report portal — Miami-Dade County | [Open source](https://county-taxes.net/fl-miamidade/reports/real-estate) · [Official evidence](https://www.miamidadeclerk.gov/clerk/property-tax-deeds.page) | Officially linked report portal; select public-lands avail for Tax, then Run Selected Report. Clerk documents the report navigation. The linked application shell loaded, but report output was not downloaded. | P1 |
| Columbia County Clerk — Columbia County | [Open source](https://columbiaclerk.com/clerk-services/tax-deeds/upcoming-tax-deed-sales/) · [Official evidence](https://columbiaclerk.com/clerk-services/tax-deeds/upcoming-tax-deed-sales/) | Public HTML page; monitor for new entries. Page explicitly said no properties on its tax deed list when reviewed. Keep as an empty feed, not as active inventory. | P3 |

## Sheriff execution sales

| Source | Public listing/data | Collection route and review notes | Priority |
|---|---|---|---|
| Palm Beach County Sheriff — Palm Beach County | [Open source](https://www.pbso.org/inside-pbso/law-enforcement/court-services-division/sheriffs-sale) · [Official evidence](https://www.pbso.org/inside-pbso/law-enforcement/court-services-division/sheriffs-sale) | Public HTML sale list; filter real estate and parse date/status. Actual property listings were readable, including scheduled and cancelled sales. Mixed with vehicles. Links to https://www.bid4assets.com/pbsosheriffsales; that page shows Download Property List but its search was temporarily unavailable in the retrieved view. | P1 |
| Orange County Sheriff — Orange County | [Open source](https://www.ocso.com/public-notices/) · [Official evidence](https://www.ocso.com/public-notices/) | Public notice index, linked HTML notices and PDFs; text extraction/OCR where necessary. Current index is readable and includes personal property notices. An official indexed real-property notice exists at https://www.ocso.com/18246/ but its direct fetch failed; it is evidence of the source type, not a verified upcoming sale. | P2 |

## State and local government property

| Source | Public listing/data | Collection route and review notes | Priority |
|---|---|---|---|
| Florida DEP, State Lands — Statewide | [Open source](https://floridadep.gov/lands/bureau-real-estate-services/content/surplus-properties) · [Official evidence](https://floridadep.gov/lands/bureau-real-estate-services/content/surplus-properties-sale) | Public HTML offer and pending-sale sections; follow bid packages when present. Both available and under-contract sections said No Current Listings. Suitable for change detection, not a source of current property volume. | P3 |
| Florida Department of Transportation — Statewide | [Open source](https://rowsurplus.fdot.gov/) · [Official evidence](https://www.fdot.gov/rightofway/PurchaseLeaseProperty.shtm) | Public search service collected 110 listings across 17 counties. Includes right-of-way surplus property; some records may be offered for lease or have other availability qualifications. Preserve the agency record ID and verify availability before treating as an active purchase opportunity. | P1 |
| Southwest Florida Water Management District — District coverage; listings in Hillsborough, Pasco and Polk observed | [Open source](https://www.swfwmd.state.fl.us/business/land-for-sale-listing) · [Official evidence](https://www.swfwmd.state.fl.us/business/land-sale) | Public HTML tables collected four offers: Hillsborough (0.56 acre), Pasco (589 acres), and Polk (5 and 77 acres). Sale terms, map links and contact details are retained where published. Restrictions differ by parcel. | P1 |
| Southwest Florida Water Management District — District coverage | [Open source](https://www25.swfwmd.state.fl.us/arcgis11/rest/services/prjSurplus/DistrictLandForSale/MapServer/1) · [Official evidence](https://www25.swfwmd.state.fl.us/arcgis11/rest/services/prjSurplus/DistrictLandForSale/MapServer/1) | Public ArcGIS REST metadata advertises Query, JSON/GeoJSON and pagination. Metadata read; successful data-query response not verified. Fields include SURPLUS_ID, PROPERTY, COUNTY, ACRES and SURPLUS_STATUS. Statuses include proposed, declared and surplused; reconcile against active HTML sale list before labeling for sale. | P1 |
| Martin County Real Property Division — Martin County | [Open source](https://www.martin.fl.us/SurplusProperty) · [Official evidence](https://www.martin.fl.us/SurplusProperty) | Public HTML inventory; follow contracted auctioneer or procurement notice. Separate pending, available and CRA sections. Available section included 5703 SE 47th Avenue, Stuart, but no auction date was verified. Donation parcels must be excluded from open-market sale inventory. | P2 |
| City of Tampa Real Estate / Purchasing — Tampa | [Open source](https://www.tampa.gov/purchasing/info/bid-schedule) · [Official evidence](https://www.tampa.gov/real-estate/info/land-for-sale) | Property RFPs in procurement bid schedule / OpenGov; filter real estate dispositions and leases. Land-for-sale page now directs to bid schedule rather than listing properties. OpenGov account required to submit responses. Listing and attachment automation not tested. | P2 |
| Miami-Dade County — Miami-Dade County | [Open source](https://www.miamidade.gov/global/service.page?Mduid_service=ser150636964589938) · [Official evidence](https://www.miamidade.gov/global/service.page?Mduid_service=ser150636964589938) | Official entry to county-owned property search and sale process; then collect specific bid notices. General inventory/disposition information, not a verified active sale feed. Ownership alone must not be interpreted as availability for sale. | P3 |

## Earlier distress signals and bulk records

| Source | Public listing/data | Collection route and review notes | Priority |
|---|---|---|---|
| Hillsborough Clerk — Hillsborough County | [Open source](https://www.hillsclerk.com/pt/records-and-reports/public-data-files) · [Official evidence](https://www.hillsclerk.com/pt/records-and-reports/public-data-files) | Official downloadable civil CSV and daily recorded-document index files; follow published layouts. Page documents monthly civil case CSV files and daily D/P/M official-record files. Filter relevant case/document types and link to parcels. Foreclosure escrow balances and excess proceeds are not upcoming property listings. | P1 |
| Miami-Dade Clerk — Miami-Dade County | [Open source](https://onlineservices.miamidadeclerk.gov/officialrecords?source=MFS) · [Official evidence](https://www.miamidadeclerk.gov/clerk/mortgage-foreclosures.page) | Official lis pendens / recorded-document search; browser form needed. Official clerk link verified; application content did not render in text fetch. Lis pendens indicates litigation affecting property, not necessarily a scheduled foreclosure or a willing seller. | P2 |
| Miami-Dade Clerk Commercial Data Services — Miami-Dade County | [Open source](https://www.miamidadeclerk.gov/clerk/commercial-data-services.page) · [Official evidence](https://www.miamidadeclerk.gov/clerk/commercial-data-services.page) | Documented authenticated API and bulk file downloads; paid service. Page expressly supports automated downloads and publishes layouts. Registration and fees apply; civil file access requires additional identity paperwork. Schema and relevant record types must be checked before subscribing. | P2 |

## Federal sources with Florida coverage

| Source | Public listing/data | Collection route and review notes | Priority |
|---|---|---|---|
| U.S. Treasury — Nationwide; filter Florida | [Open source](https://www.treasury.gov/auctions/treasury/rp/realprop.shtml) · [Official evidence](https://www.treasury.gov/auctions/treasury/rp/index.shtml) | One Florida property collected: 106 SW 10th Avenue, South Bay, scheduled September 23, 2026; $40,000 starting bid, $10,000 deposit, parcel ID and property facts. Detail page: https://www.treasury.gov/auctions/treasury/rp/106southbay.shtml. Federal agency, not Florida state government. Starting bid is not a foreclosure judgment amount. | P1 |
| U.S. HUD — Nationwide; filter Florida | [Open source](https://www.hudhomestore.gov/) · [Official evidence](https://www.hud.gov/helping-americans/hudhomes-how-to-sell) | Public property search; browser testing required for Florida results and details. Official HUD listing destination verified. Search shell was readable, but Florida inventory was not collected. Government-owned foreclosed homes; do not substitute similarly named commercial websites. | P2 |
| U.S. General Services Administration — Nationwide; filter Florida | [Open source](https://realestatesales.gov/) · [Official evidence](https://www.gsa.gov/real-estate/real-property-disposition) | Official auction destination; also monitor https://disposal.gsa.gov/RecentProperty. Agency confirms real estate sales, including land and buildings. RecentProperty text was readable but contained closed listings; no current Florida count established. | P2 |
| Internal Revenue Service — Nationwide; filter Florida and real estate | [Open source](https://www.irsauctions.gov/auction/items/) · [Official evidence](https://www.irsauctions.gov/) | Official upcoming-auction application; inspect filters and linked notice documents. Official entry and upcoming-auction shell read. No active Florida real-estate inventory verified. Separate from Treasury criminal-forfeiture real estate auctions. | P2 |
| U.S. Marshals Service / contracted real estate provider — Nationwide; filter Florida | [Open source](https://reallook.com/) · [Official evidence](https://www.usmarshals.gov/what-we-do/asset-forfeiture) | Agency-designated contractor listings; confirm source attribution and browser access. USMS page explicitly identifies RealLook as its real-property national contractor website. Contractor listings were not queried in this review. | P2 |

## Statewide expansion directory

| Source | Public listing/data | Collection route and review notes | Priority |
|---|---|---|---|
| Florida Court Clerks & Comptrollers — Florida counties | [Open source](https://www.flclerks.com/page/sunshineweek) · [Official evidence](https://www.flclerks.com/page/sunshineweek) | Official association directory of county clerk websites and records contacts. Use to expand county coverage and locate public exports or request existing electronic lists. Directory is not itself a property listing feed. | P2 |

## Implemented collection snapshot — September 21, 2026

The new public-feed snapshot contains 115 Florida real-estate listings: 110 FDOT records, four SWFWMD land offers, and one U.S. Treasury auction. The application also retains earlier Columbia County foreclosure and Palm Beach Sheriff real-estate imports. These are source-specific public listings, not a complete inventory of all Florida county foreclosure or tax-deed auctions.

Records retain the agency/source URL, source record or parcel identifier, sale type, observed date, and available property details. Judgment amounts are left blank unless the source actually publishes a judgment; starting bid, acreage, assessed value, and liens are not substituted for it. FDOT duplicate property numbers remain separate when they have different agency record IDs.

## Data model and collection rules

Capture the source and agency, county, sale type, source record ID, case number, parcel ID, address/legal description, sale date/time and timezone, status, judgment, opening bid, asking price, source/document URLs and observation timestamps. Retain each original record and document for provenance.

Use county + parcel ID to link property records, and source record/case + sale event to distinguish auctions. Preserve cancellations, redemptions and rescheduling. Do not merge judgment amount with opening bid or assessed value.

Tax lien certificates represent liens; tax deed auctions concern property. Lis pendens and new foreclosure filings are early signals, not current sale offers. Surplus proceeds concern money after a sale. Agency ownership and proposed-surplus status alone do not establish an active public sale.

Prefer official exports and documented APIs to screen scraping. Check each source’s automation/reuse terms and retain normal access controls. For a feed without a practical export, request the agency’s existing electronic list and field definitions.

Suggested refresh: daily for auctions and notices, with a status recheck near sale time; weekly for low-volume government surplus pages. These are design recommendations, not verified publisher update schedules.

## Remaining verification

County vendor portals need a normal-browser test of unauthenticated calendars, detail pages, result pagination and downloadable lists. The FDOT GIS export and SWFWMD GIS query are separate from the public feeds collected above and still need validation if we use those GIS endpoints for parcel enrichment. Hillsborough bulk layouts need a check of foreclosure and lis pendens codes. Federal portals other than Treasury need Florida inventory checks. None of these remaining checks should be represented as completed.
