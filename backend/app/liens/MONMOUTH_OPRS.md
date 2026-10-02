# Monmouth County public lien source

The first county adapter uses the [Monmouth County Clerk Open Public Records
Search System](https://oprs.co.monmouth.nj.us/Oprs/clerk/ClerkHome.aspx?op=basic).
The county publishes a free public index search by block/lot and owner. The
index exposes mortgages, mortgage discharges/cancellations, assignments, lis
pendens, federal and municipal liens, construction liens, tax-sale records,
deeds, and related recorded document types.

The adapter uses block/lot and municipality when available, then falls back to
the defendant/current-owner name. It stores the returned public row in both
`raw_public_records` and the existing `raw_lien_records` audit table, and
normalizes supported document rows into `property_liens`. Matching remains
conservative: owner-only matches remain low confidence and require manual
review. Mortgage/discharge references create `lien_relationships` when the
public row contains the parent instrument number.

The county warns that the online data is informational and that title searches
must be made in person. The adapter therefore does not fetch protected images,
authenticate, solve challenges, or claim that a document is active, released,
senior, or surviving. A blocked or unreliable request is returned as
`MANUAL_REVIEW_REQUIRED` with the parcel, owner, address, source URL, and
recommended search terms. A successful search with no rows is stored as
`CHECKED_NO_MATCH`; it never means clean title.
