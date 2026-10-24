# Pima County Recorder and Assessor: trustee-sale data

Checked 2026-10-24 in a visible Chrome window with an operator present. Nothing here needed an account.

## Recorder: Tyler EagleWeb ("Self-Service Web")

`https://pimacountyaz-web.tylerhost.net/web/`

| Check | Finding |
|---|---|
| robots.txt | None (4xx), so nothing is disallowed (RFC 9309) |
| Terms | The disclaimer covers indemnity, "subject to change" and the index being a guide only. It sets no terms on automated use. |
| Disclaimer | Has a Google reCAPTCHA ("I'm not a robot") before **I Accept**. The operator ticks it, never a script. |
| Bot control | **AWS WAF.** Searches and result pages requested from a script (even inside the accepted browser session) answer `405` with an AWS "Human Verification" page. The site's own buttons sometimes get the same answer in an automated browser. |

Under AGENTS.md (a site that keeps challenging an automated browser after the operator passed is declining automation), Pima is collected by **manual export**. The operator saves the documents from a normal browser, and the collector reads the saved PDFs. Nothing scripted runs against the portal.

### Document types (Document Type Search)

Pima names its types without "of":

| Kind | Type names | Code |
|---|---|---|
| Notice of Trustee's Sale | NOTICE SALE, AMENDED NOTICE SALE | `NTSALE`, `ANTSAL` |
| Cancellation of the notice | CANCELLATION NOTICE SALE | `CNLNT` |
| Trustee's deed (of any kind) | TRUSTEES DEED, AMENDED TRUSTEES DEED | |

Volume: 32 NOTICE SALE recordings from Oct 17 to Oct 24, 2026, about 30 to 40 a week. The index is certified a few days behind ("certified ... through Oct 20, 2026" on Oct 24).

### What the portal shows

- **Result rows:** recording number, type, recording date, and grantor and grantee names (the borrower and trustee). An index entry adds the parcel ID, the situs address, the subdivision and lot, and related documents such as the deed of trust a notice enforces.
- **Document viewer:** every page as a free, watermarked "Unofficial Copy", with a download button. The download is named after the recording number (`20262940537.pdf`). Certified copies cost money ("Purchase") and aren't needed.

### Notice layouts seen (7 notices, 4 layouts)

| Trustee | Sale date | Address label | APN |
|---|---|---|---|
| Quality Loan Service | "Sale Date and Time: \| 2/10/2027 at 10:00 AM" | "Purported Street Address:" | "Tax Parcel Number: 136-17-5140" |
| Individual trustee (Alpharetta, GA) | "Sale Date: \| 01/27/2027" and "Sale Time: \| 11:30 AM" on page 2 | "STREET ADDRESS or IDENTIFIABLE LOCATION:" | "COUNTY ASSESSOR'S TAX PARCEL NUMBER: 212174380" (no dashes) |
| Tiffany & Bosco | in the prose: "on January 27, 2027 at 10:00 AM" | "...is purported to be:" with the address on the next two lines | "Tax Parcel No.:" |
| Total Lender Solutions, Prestige Default (Ghidotti) | in the prose: "on 01/21/2027 at 11:30 AM" | "Street address or identifiable location:" | "A.P.N.:" |

Every sale is at the Superior Court building, 110 W. Congress, Tucson. Pima APNs are 3-2-4 (`136-17-5140`); the Maricopa 3-2-3 pattern would cut the last digit. The original trustor's mailing address can differ from the property, so only the labelled property address is used. One beneficiary was a private family trust, which isn't kept (only companies are).

## Assessor parcels

`https://gisdata.pima.gov/arcgis1/rest/services/GISOpenData/LandRecords/MapServer/0` (Parcel Centroids). It's open, has no robots.txt and has no WAF.

| Field | Use |
|---|---|
| `PARCEL` | APN without dashes (`136175140`) |
| `ADDRESS_OL`, `ZIP` | Situs street and ZIP (no postal city; `JURIS_OL` is the jurisdiction, e.g. "UNINCORPORATED PIMA COUNTY") |
| `LAT`, `LON` | Position |
| `FCV`, `LIMNET`, `TAXYR` | Full cash value, limited net value, tax year (floats) |
| `PARCEL_USE` | Use code |
| `MAIL1`–`MAIL5` | Owner mailing lines: **never requested** |

There's no legal-class field, so Pima listings have no owner-occupied flag.

## Weekly run (operator's Mac)

1. Open the portal in a normal browser, tick the reCAPTCHA and accept.
2. Search the week's recording dates once per type: NOTICE SALE, AMENDED NOTICE SALE, CANCELLATION NOTICE SALE, TRUSTEES DEED. Open each result and click the viewer's download button, saving everything into one folder (e.g. `~/Downloads/pima`). Files already imported are skipped, so overlapping weeks are fine.
3. Run:

```bash
python -m pipeline.scrape_az_trustee_sales --county Pima --import-folder ~/Downloads/pima
python -m pipeline.load_az_trustee_sales --county Pima --dry-run
python -m pipeline.load_az_trustee_sales --county Pima
```

The import reads each PDF's recording number (from the file name, otherwise the recorder's stamp), its recording date (from the stamp) and its kind (from its title). A file without all three is listed as unrecognised and isn't indexed. OCR, parsing, linking, parcels and the snapshot (`data/sheriff_sales/az_pima_trustee_sales.json`) then work as for Maricopa. The PDFs and OCR text stay in `.local/az-recorder/pima/`.
