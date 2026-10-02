# New Jersey preliminary lien source matrix

This inventory is a routing and coverage aid for preliminary screening. A
source marked `NOT_FOUND` or `MANUAL_ONLY` does not mean that the property is
clear. County and municipal systems change independently; URLs and access
behavior should be re-checked before each adapter is enabled.

## County land-record sources

| County | Official source / search URL | Parcel or block/lot | Owner search | Documents commonly exposed | Automation status |
|---|---|---:|---:|---|---|
| Atlantic | [County Clerk](https://www.atlantic-county.org/countyclerk/) | Unknown | Unknown | Deeds, mortgages, liens | UNKNOWN |
| Bergen | [County Clerk](https://www.bergencountyclerk.gov/) | Possible | Possible | Deeds, mortgages, assignments | POSSIBLE |
| Burlington | [County Clerk](https://www.co.burlington.nj.us/192/County-Clerk) | Unknown | Unknown | Deeds, mortgages, liens | MANUAL_ONLY |
| Camden | [County Clerk](https://www.camdencounty.com/service/county-clerk/) | Possible | Possible | Deeds, mortgages, liens | POSSIBLE |
| Cape May | [County Clerk](https://capemaycountynj.gov/242/County-Clerk) | Unknown | Unknown | Deeds, mortgages, liens | MANUAL_ONLY |
| Cumberland | [County Clerk](https://www.cumberlandcountynj.gov/CountyClerk) | Unknown | Unknown | Deeds, mortgages, liens | MANUAL_ONLY |
| Essex | [County Clerk](https://www.essexclerk.com/) | Possible | Possible | Deeds, mortgages, lis pendens | POSSIBLE |
| Gloucester | [County Clerk](https://www.gloucestercountynj.gov/CountyClerk) | Unknown | Unknown | Deeds, mortgages, liens | MANUAL_ONLY |
| Hudson | [County Clerk](https://www.hudsoncountyclerk.org/) | Unknown | Unknown | Deeds, mortgages, liens | MANUAL_ONLY |
| Hunterdon | [County Clerk](https://www.co.hunterdon.nj.us/countyclerk/) | Unknown | Unknown | Deeds, mortgages, liens | MANUAL_ONLY |
| Mercer | [County Clerk](https://www.mercercounty.org/government/county-clerk) | Unknown | Unknown | Deeds, mortgages, liens | MANUAL_ONLY |
| Middlesex | [County Clerk](https://www.middlesexcountynj.gov/government/departments/county-clerk) | Possible | Possible | Deeds, mortgages, liens | POSSIBLE |
| Monmouth | [OPRS public index](https://oprs.co.monmouth.nj.us/Oprs/clerk/ClerkHome.aspx?op=basic) | Yes | Yes | Deeds, mortgages, discharges, assignments, lis pendens, tax/municipal lien labels | SUPPORTED |
| Morris | [County Clerk](https://www.morriscountyclerk.org/) | Unknown | Unknown | Deeds, mortgages, liens | MANUAL_ONLY |
| Ocean | [County Clerk](https://www.co.ocean.nj.us/OC/CountyClerk/) | Possible | Possible | Deeds, mortgages, liens | POSSIBLE |
| Passaic | [County Clerk](https://www.passaiccountynj.org/government/county-clerk) | Unknown | Unknown | Deeds, mortgages, liens | MANUAL_ONLY |
| Salem | [County Clerk](https://www.salemcountynj.gov/departments/county-clerk/) | Unknown | Unknown | Deeds, mortgages, liens | MANUAL_ONLY |
| Somerset | [County Clerk](https://www.somersetcountynj.gov/government/elected-officials/county-clerk) | Unknown | Unknown | Deeds, mortgages, liens | MANUAL_ONLY |
| Sussex | [County Clerk](https://sussexcountyclerk.com/) | Unknown | Unknown | Deeds, mortgages, liens | MANUAL_ONLY |
| Union | [County Clerk](https://ucnj.org/county-clerk/) | Unknown | Unknown | Deeds, mortgages, liens | MANUAL_ONLY |
| Warren | [County Clerk](https://www.warrencountynj.org/departments/county-clerk/) | Unknown | Unknown | Deeds, mortgages, liens | MANUAL_ONLY |

`SUPPORTED` currently means that SheriffSale has a normal public HTTP adapter
and parser. `POSSIBLE` means the official portal may support a future adapter
but has not passed an automation and coverage review. `MANUAL_ONLY` and
`UNKNOWN` are surfaced as review states rather than queried automatically.
Each registry entry also records its freshness behavior: a retrieval timestamp
is retained even when the source does not publish a reliable last-updated date.

## State and municipal sources

- [NJGIN / NJ Open Data](https://njgin.nj.gov/) and the NJ MOD-IV parcel data
  are identity and assessment sources. They are not treated as a lien database.
- Municipal tax, tax-sale, water, sewer, stormwater, and special-assessment
  systems are municipality or authority specific. The current registry routes
  these to `MANUAL_REVIEW_REQUIRED` until an official public endpoint is
  verified.
- NJ Judiciary, NJ UCC, HOA/condominium, and federal/state tax-lien searches
  remain explicit coverage categories. They are not inferred from an absent
  county record.

## Current SheriffSale coverage

The first end-to-end county adapter is Monmouth County OPRS. It searches by
municipality/block/lot where available and falls back to owner name. It stores
raw rows, source identifiers, hashes, normalized document types, conservative
property/owner matching, and mortgage/discharge relationships. Other counties
are intentionally routed to `POSSIBLE` or `MANUAL_ONLY` until their public
access and field coverage are verified.
