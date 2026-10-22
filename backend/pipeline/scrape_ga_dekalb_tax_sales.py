"""DeKalb County, GA tax sales from the Tax Commissioner's tax sale listing.

The DeKalb County Tax Commissioner sells tax-delinquent property at the courthouse on the
first Tuesday of the month and lists the parcels on its property search site
(publicaccess.dekalbtaxga.gov, "Tax Sale List"; the page frames
content/search/tax_sale_listing.html, a plain HTML table): sale date, parcel ID, tax sale ID,
address, levy type and date, lien book/page, tax years and total tax due. The table also
names the owner, tenant and defendant; those columns are never read.

Each parcel's city, ZIP and map position come from the county's public parcel layer
(dcgis.dekalbcountyga.gov HansenParcels; only the parcel ID, site address fields and shape
are requested). No OCR is involved, so this runs in the Monday multistate refresh. The
snapshot has the shape of scrape_ga_tax_sales' and loads with load_ga_tax_sales:

    python -m pipeline.scrape_ga_dekalb_tax_sales
    python -m pipeline.load_ga_tax_sales --input data/sheriff_sales/ga_dekalb_tax_sales.json
"""
import argparse
import html
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

from pipeline.scraping.config import ScrapingSettings
from pipeline.scraping.http import PoliteClient

LIST_URL = "https://publicaccess.dekalbtaxga.gov/content/search/tax_sale_listing.html"
PAGE_URL = "https://publicaccess.dekalbtaxga.gov/forms/htmlframe.aspx?mode=content/search/tax_sale_listing.html"
PARCEL_LAYER = "https://dcgis.dekalbcountyga.gov/mapping/rest/services/Hansen/HansenParcels/MapServer/0/query"
OUTPUT = Path("data/sheriff_sales/ga_dekalb_tax_sales.json")
PARSER_VERSION = "ga_dekalb_tax_sale_listing_v1"
# The table's columns; owner, tenant and defendant (4, 6, 7) are skipped.
KEPT = {0: "sale_date", 1: "parcel", 3: "tax_sale_id", 5: "street", 8: "levy_type", 9: "lien_book", 10: "lien_page",
        11: "levy_date", 12: "min_year", 13: "max_year", 14: "total_tax_due"}
ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S | re.I)


def rows(page: str) -> list[dict]:
    found = []
    for row in ROW.findall(page):
        cells = [" ".join(html.unescape(re.sub(r"<[^>]+>", " ", cell)).split()) for cell in CELL.findall(row)]
        if len(cells) >= 15 and re.fullmatch(r"\d{2}-[A-Z]{3}-\d{4}", cells[0]):
            found.append({field: cells[index] for index, field in KEPT.items()})
    return found


def layer_places(client: PoliteClient, parcels: list[str]) -> dict[str, dict]:
    """Site address, city, ZIP and centroid per parcel ID (no owner or mailing fields are requested)."""
    found = {}
    for start in range(0, len(parcels), 50):
        batch = parcels[start:start + 50]
        response = client.post(PARCEL_LAYER, data={
            "where": f"PARCELID IN ({','.join(repr(value) for value in batch)})",
            "outFields": "PARCELID,ADDRESS_NUMBER,FULL_STREET_NAME,UNIT_NO,CITY,ZIP", "returnGeometry": "true",
            "outSR": "4326", "f": "json"})
        response.raise_for_status()
        for feature in response.json().get("features") or []:
            row, ring = feature["attributes"], ((feature.get("geometry") or {}).get("rings") or [[]])[0]
            street = " ".join(str(part) for part in (row.get("ADDRESS_NUMBER"), row.get("FULL_STREET_NAME"),
                                                     row.get("UNIT_NO")) if part)
            found[row["PARCELID"]] = {
                "street": street or None, "city": (row.get("CITY") or "").strip().title() or None,
                "zip_code": (row.get("ZIP") or "").strip()[:5] or None,
                "latitude": sum(point[1] for point in ring) / len(ring) if ring else None,
                "longitude": sum(point[0] for point in ring) / len(ring) if ring else None}
    return found


def parcel_from(row: dict, place: dict | None) -> dict:
    sale_date = datetime.strptime(row["sale_date"], "%d-%b-%Y").date().isoformat()
    due = re.sub(r"[^\d.]", "", row["total_tax_due"])
    place = place or {}
    return {"county": "DeKalb", "sale_date": sale_date, "list_url": PAGE_URL, "parcel": row["parcel"],
            "parcel_as_listed": row["parcel"], "sale_number": row["tax_sale_id"],
            "street": place.get("street") or row["street"], "street_as_listed": row["street"],
            "city": place.get("city"), "zip_code": place.get("zip_code"),
            "starting_bid": float(due) if due else None, "levy_type": row["levy_type"],
            "levy_date": row["levy_date"], "tax_years": f"{row['min_year']}-{row['max_year']}",
            "lien": f"{row['lien_book']}/{row['lien_page']}",
            "latitude": place.get("latitude"), "longitude": place.get("longitude"),
            "matched_by": "parcel_id" if place else None}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    with PoliteClient(ScrapingSettings.from_env()) as client:
        page = client.get(LIST_URL)
        page.raise_for_status()
        listed = rows(page.text)
        places = layer_places(client, sorted({row["parcel"] for row in listed}))
    today = date.today().isoformat()
    parcels = [parcel_from(row, places.get(row["parcel"])) for row in listed]
    parcels = [parcel for parcel in parcels if parcel["sale_date"] >= today]
    if "Tax Sale Date" not in page.text:
        raise SystemExit(f"DeKalb tax sale list: the table is missing on {LIST_URL}; previous snapshot kept")
    snapshot = {"source_system": "ga_county_tax_sale", "state": "GA", "scraped_at": datetime.now(timezone.utc).isoformat(),
                "parser_version": PARSER_VERSION, "counties": ["DeKalb"], "failed": [], "parcels": parcels,
                "unmatched": [f"DeKalb {p['parcel']} ({p['street_as_listed']})" for p in parcels if not p["matched_by"]]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, indent=1) + "\n")
    print(f"DeKalb: {len(listed)} listed, {len(parcels)} upcoming, {len(snapshot['unmatched'])} without a parcel match"
          f" -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
