"""Bexar County, TX trustee-sale notices from the County Clerk's foreclosure map.

The Bexar County Clerk maps the Notices of Trustee's Sale filed for each month's sale
(maps.bexar.org/foreclosures, updated about 18 days before the sale and again after it).
Its ArcGIS service lists each notice's document number, sale month, street address,
city, ZIP and position, with no party names, so nothing needs OCR. Layer 0 holds the
mortgage foreclosures; the property-tax notices (layer 1) are left to the tax-sale
sources. Sales are on the first Tuesday of the month.

The snapshot has the same shape as scrape_harris_trustee_notices' and loads with
load_tx_trustee_sales:

    python -m pipeline.scrape_bexar_trustee_notices
    python -m pipeline.load_tx_trustee_sales --input data/sheriff_sales/tx_bexar_trustee_notices.json
"""
import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path

from pipeline.scrape_harris_trustee_notices import first_tuesday
from pipeline.scraping.config import ScrapingSettings
from pipeline.scraping.http import PoliteClient

MAP_URL = "https://maps.bexar.org/foreclosures/"
LAYER_URL = "https://maps.bexar.org/arcgis/rest/services/CC/ForeclosuresProd/MapServer/0/query"
FIELDS = "DOC_NUMBER,YEAR,MONTH,ADDRESS,CITY,ZIP,TYPE"
PAGE = 1000  # the service's maxRecordCount
OUTPUT = Path("data/sheriff_sales/tx_bexar_trustee_notices.json")
PARSER_VERSION = "tx_bexar_foreclosure_map_v1"


def notices_from(features: list[dict], today: date) -> list[dict]:
    """Mortgage notices for a sale day from today on, one per document number."""
    notices = {}
    for feature in features:
        row, point = feature.get("attributes") or {}, feature.get("geometry") or {}
        if (row.get("TYPE") or "").upper() != "MORTGAGE" or not (row.get("YEAR") and row.get("MONTH")):
            continue
        sale_date = first_tuesday(int(row["YEAR"]), int(row["MONTH"]))
        doc = str(row.get("DOC_NUMBER") or "").strip()
        if sale_date < today or not doc:
            continue
        notices[doc] = {
            "doc_id": doc, "sale_date": sale_date.isoformat(), "file_date": None,
            "street": " ".join((row.get("ADDRESS") or "").split()).title() or None,
            "city": (row.get("CITY") or "").strip().title() or None,
            "zip_code": str(row.get("ZIP") or "").strip()[:5] or None,
            "address_source": "clerk_map", "notice_kind": "deed_of_trust",
            "latitude": point.get("y"), "longitude": point.get("x"),
        }
    return sorted(notices.values(), key=lambda notice: (notice["sale_date"], notice["doc_id"]))


def fetch(client: PoliteClient) -> list[dict]:
    features, offset = [], 0
    while True:
        response = client.get(LAYER_URL, params={
            "where": "1=1", "outFields": FIELDS, "returnGeometry": "true", "outSR": "4326",
            "orderByFields": "OBJECTID", "resultOffset": offset, "resultRecordCount": PAGE, "f": "json"})
        response.raise_for_status()
        payload = response.json()
        if "error" in payload:
            raise RuntimeError(f"Bexar foreclosure map: {payload['error']}")
        batch = payload.get("features") or []
        features += batch
        if not payload.get("exceededTransferLimit") or not batch:
            return features
        offset += len(batch)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    with PoliteClient(ScrapingSettings.from_env()) as client:
        notices = notices_from(fetch(client), date.today())
    if not notices:
        # An empty map between updates must not retire anything: keep the last snapshot.
        raise SystemExit("Bexar foreclosure map: no upcoming mortgage notices; previous snapshot kept")
    snapshot = {
        "source_system": "tx_county_clerk_trustee_sale", "state": "TX", "county": "Bexar", "source_url": MAP_URL,
        "scraped_at": datetime.now(timezone.utc).isoformat(), "parser_version": PARSER_VERSION,
        "sale_months": sorted({notice["sale_date"][:7] for notice in notices}), "complete": True,
        "notices": notices, "failures": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, indent=1) + "\n")
    print(f"Bexar: {len(notices)} upcoming mortgage foreclosure notices -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
