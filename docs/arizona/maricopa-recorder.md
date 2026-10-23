# Maricopa County Recorder and Assessor: endpoints for trustee-sale data

Checked 2026-10-23 with plain HTTP requests (1 request per ~1.2 s, a descriptive User-Agent). Nothing here needed an account.

## Recorder

| Host | robots.txt | Automated access |
|---|---|---|
| `recorder.maricopa.gov` (the public search website) | Not readable: every path, including `/robots.txt`, answers 403 with a Cloudflare managed challenge ("Just a moment...") | **No.** A script would have to pass Cloudflare's bot check, which this project does not do (see AGENTS.md, Access controls). |
| `publicapi.recorder.maricopa.gov` (the JSON API behind the website) | 404 (no file), so nothing is disallowed | Yes, for the index endpoints below. |
| `legacy.recorder.maricopa.gov` | `Disallow: /recdocdata/` (the document images) | Not for images. |

The API publishes its OpenAPI spec at `https://publicapi.recorder.maricopa.gov/api-docs`. No terms of use are published on the API host. The website's terms can't be read because of the Cloudflare check. No rate-limit headers are returned.

### Document codes (`GET /documentcodes/all`)

The search's `documentCode` takes the **short code**; the long code returns nothing.

| Document | Long code | Short code |
|---|---|---|
| Notice of Trustee's Sale | `N/TR SALE` | `NS` |
| Cancellation of Notice of Trustee's Sale | `C/N D/T` | `CQ` |
| Trustee's Deed (of any kind, including Trustee's Deed Upon Sale) | `TRST DEED` | `TD` |
| Rescission of Trustee's Deed or other | `RESCIND` | `NZ` |
| Substitution of Trustee on Deed of Trust | `SUB TRSTE` | `ST` |
| Deed of Trust | `DEED TRST` | `DT` |

### Search by type and recording date

```
GET /documents/search?documentCode=NS&beginDate=2026-10-01&endDate=2026-10-07&pageNumber=1&pageSize=200
```

- Response: `{"searchResults": [{"names", "recordingNumber", "recordingSuffix", "recordingDate" (MM-DD-YYYY), "documentCode" (long code), "docketBook", "pageMap"}], "totalResults"}`.
- `pageSize` is at most 200 (a larger value answers 400 "must be less than or equal to 200").
- `totalResults` is capped at 501 ("more than 500"), and pages after the first report `-1`, though they still return rows. **Query one week at a time** so a window stays under 500 and paging is complete.
- `names` holds the parties' names (for a notice, the trustor/borrower). The ingester must not store them (see Privacy).
- Volumes: notices run at about 430–460 a month (Jul 437, Aug 431, Sep 456 for days 1–28). The 120 days to 2026-10-22 have more than 500 of each of NS, CQ and TD, and 13 NZ.

### One document

```
GET /documents/{recordingNumber}
→ {"names", "documentCodes", "recordingDate", "recordingNumber", "pageAmount", "docketBook", "pageMap",
   "affidavitPresent", "affidavitPageAmount", "restricted"}
```

There's no address, APN, legal description, amount or cross-reference in the index. Those are only in the document image.

### Document images: not available to a script

| Endpoint | Result without a browser session |
|---|---|
| `GET /preview/image?recordingNumber=…&pageNumber=1` | 403 Forbidden |
| `GET /preview/pdf-link?recordingNumber=…` | 403 "PDF preview is not available." |
| `GET /preview/pdf?recordingNumber=…&token=…` | Needs a `token` |
| `GET /preview/session?recordingNumber=…&pages=…&ts=…&sig=…` → `/preview/image-secure?…&previewSessionId=…` | Needs a timestamp and signature issued by the Cloudflare-protected website |

Images are served only through a signed preview session that the website issues after its bot check. Forging or replaying that signature, or passing the check automatically, would be bypassing an access control. The legacy host's robots.txt disallows its image folder. So an unattended daily job can index the recordings, but it **can't read them**. Ways to get the text without breaking those rules:

1. **Operator-assisted run:** the project's `BrowserManager --assisted` pattern. The operator opens the Recorder in a visible browser and passes the check, and the run then opens each notice the normal way and saves its pages. If Cloudflare keeps challenging the automated browser after the operator has passed, the site is declining automation, and we fall back to option 2.
2. **Manual save:** like the NY court PDFs. The operator saves the notices' PDFs into a folder, and a loader OCRs and parses them.
3. **No document text:** trustee's deeds can still be placed on their parcel through the Assessor's `DEED_NUMBER` (below). Notices can't, because the index has no property reference.

**Update, 2026-10-23 (after testing in a browser):** a real Chrome passes the site's Cloudflare check in the background with no CAPTCHA, while headless Chrome is challenged. The website's "Unofficial PDF" button calls `GET /preview/pdf-link` from the page, which returns a short-lived `/preview/pdf?…&token=…` URL. That URL then **redirects (302) to `https://legacy.recorder.maricopa.gov/recdocdata/unofficialpdfdocs.aspx?rec=…`, the path the legacy host's robots.txt disallows.** So every document PDF is served from a robots-disallowed path, and automated fetching of the documents is not allowed by the Recorder's robots.txt, even through the website's own button flow.

- The legacy robots.txt answers scripts with a Cloudflare 403 page, and the shared `RobotsPolicy` used to read that as "no robots.txt" (allowed). It now treats a verification page served in place of robots.txt as unreachable (disallowed), and `DocumentFetcher` checks robots.txt on every redirect hop. The fetch stage stops with `RobotsDisallowed` before downloading anything.
- A first backfill attempt fetched 143 documents before this was caught (stopped by a timeout on the legacy host). They are in `.local/az-recorder/maricopa/pdf/` and `ocr/`.

Remaining ways to read the documents without automated access to `/recdocdata/`:
1. **Permission or a data product from the Recorder:** ask for written permission, or use the Recorder's paid document-download access (`/purchase/download-access.html`, which needs an account).
2. **Manual save:** the operator opens each new notice in a normal browser and saves the PDF into a folder, and the existing OCR, parse, link and load stages take it from there (`--no-fetch`). That's about 20 notices a working day for Maricopa, plus cancellations and deeds.
3. **No document text:** keep the unattended index pull (counts per day) and link trustee's deeds to parcels through the Assessor's `DEED_NUMBER`.

## Assessor

| Host | robots.txt | Use |
|---|---|---|
| `mcassessor.maricopa.gov` (website and its API) | Disallows `/mcs/` and query-string pages | The website's search answered 500 to scripted requests. The Assessor's documented API needs a token requested from the Assessor (an account step: not used). |
| `gis.mcassessor.maricopa.gov/arcgis/rest/services/Parcels/MapServer/0` (ArcGIS layer "Parcels") | 404 (no file) | **Yes.** Open ArcGIS REST query; `maxRecordCount` 1000. |

Fields worth requesting (`outFields` lists only these; owner and mailing fields are never requested):

| Field | Meaning |
|---|---|
| `APN`, `APN_DASH` | Parcel number (`133-31-137`) |
| `PHYSICAL_ADDRESS`, `PHYSICAL_STREET_*`, `PHYSICAL_CITY`, `PHYSICAL_ZIP`, `LATITUDE`, `LONGITUDE` | Situs address and position |
| `FCV_CUR`, `LPV_CUR`, `TAX_YR_CUR` | Full cash value and limited property value (text with spaces and commas, e.g. `"     394,100"`) |
| `PUC` | Property use code (`0131` single-family residence, `0819` ...) |
| `LC_CUR` | Legal class: `3.1` = owner-occupied primary residence, `4.x` = rental/secondary residential. This gives the owner-occupied flag without any names. |
| `DEED_NUMBER`, `DEED_DATE`, `SALE_PRICE` | Recording number and date of the parcel's latest deed |
| `SUBNAME`, `LOT_NUM`, `BLOCK`, `TRACT`, `MCR_BOOK`, `MCR_PAGE` | Subdivision, lot and plat reference, for matching a notice's legal description |

Field names present but not to be used: `OWNER_NAME`, `INCAREOF`, `MAIL_*`, `MAIL_ADDRESS`.

**Trustee's deeds link to parcels by deed number:** `where=DEED_NUMBER IN ('20260399413', …)` matched 19 of 40 trustee's deeds recorded in July 2026. The rest have probably been replaced by a later resale deed, or the Assessor hasn't processed them yet.

## Privacy (AGENTS.md)

Public-record importers in this project exclude owner, mailing, grantor/grantee and party fields. So:

- the Recorder index's `names` are never stored;
- the Assessor's owner and mailing fields are never requested;
- from document text, only the property, sale and loan facts are kept, plus the trustee and beneficiary (companies), as the Texas trustee loader keeps the lender. Trustor names and trustee's-deed buyers are left out.
