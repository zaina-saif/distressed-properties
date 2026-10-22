"""Clark County, NV treasurer trustee (tax) auction from the Treasurer's auction list.

Property with taxes unpaid for three years is deeded to the Clark County Treasurer as
trustee, and the Treasurer auctions it once a year (in person, at the Government Center
in Las Vegas; a 2 p.m. re-auction follows the morning sale). The Treasurer's auction page
(treasurer.clarkcountynv.gov/auction/Auction/AuctionList, no robots.txt, no CAPTCHA) loads
the current auction's sessions and parcels from two JSON endpoints, Event_Read and
Parcel_Read: parcel number, minimum bid, situs street, whether the parcel is struck from
the list, and the winning bid once sold. The parcel rows also carry the owner's name,
which is dropped here.

Situs streets have no city or ZIP, so each parcel's city code, ZIP and map position come
from the county's public parcel layer (CC_PARCELS_SHP on ArcGIS Online), asked only for
those fields. Parcels without a street ("UNASSIGNED SITUS", mostly vacant land) are kept
in the snapshot but not loaded.

    python -m pipeline.scrape_nv_clark_tax_auction
    python -m pipeline.load_nv_clark_tax_auction
"""
import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from pipeline.scraping.config import ScrapingSettings
from pipeline.scraping.http import PoliteClient

BASE = "https://treasurer.clarkcountynv.gov/auction/Auction"
LIST_URL = f"{BASE}/AuctionList"
PARCEL_LAYER = ("https://services1.arcgis.com/F1v0ufATbBQScMtY/ArcGIS/rest/services/CC_PARCELS_SHP/"
                "FeatureServer/1/query")
OUTPUT = Path("data/sheriff_sales/nv_clark_tax_auction.json")
PARSER_VERSION = "nv_clark_treasurer_auction_v1"
GRID = {"sort": "", "page": 1, "pageSize": 5000, "group": "", "filter": ""}
# Fields kept from Parcel_Read; Owner is not among them.
KEPT = ("ParcelNumber", "MinBidAmount", "PropertyLocation", "IsLineOut", "WinningBidAmount", "DeedRecordingDate")
# The parcel layer's STRCITY codes and their mailing cities. Unincorporated towns
# (Paradise, Spring Valley, Sunrise Manor, Whitney, Winchester, Summerlin South) mail as Las Vegas.
CITY_CODES = {"LV": "Las Vegas", "NLV": "North Las Vegas", "HEND": "Henderson", "BC": "Boulder City",
              "MES": "Mesquite", "PAR": "Las Vegas", "SPRV": "Las Vegas", "SUN": "Las Vegas", "WHI": "Las Vegas",
              "WIN": "Las Vegas", "SUM": "Las Vegas", "LAUG": "Laughlin", "MOAP": "Moapa", "BUNK": "Bunkerville",
              "SRCH": "Searchlight", "ISPR": "Indian Springs"}
ZIP_CITIES = {"89040": "Overton", "89021": "Logandale", "89025": "Moapa", "89019": "Jean", "89039": "Cal Nev Ari",
              "89046": "Searchlight", "89007": "Bunkerville", "89018": "Indian Springs", "89029": "Laughlin"}
LOOKUP_BATCH = 100


def auction_id(page: str) -> int:
    match = re.search(r"Parcel_Read\?auctionId=(\d+)", page)
    if not match:
        raise RuntimeError(f"No auction id on {LIST_URL}; the page layout may have changed")
    return int(match.group(1))


def apn(parcel_number: str) -> str:
    """'059-09-301-024' -> '05909301024', the parcel layer's PARCEL."""
    return re.sub(r"\D", "", parcel_number or "")


def city_of(code: str | None, zip_code: str | None) -> str | None:
    if zip_code in ZIP_CITIES:
        return ZIP_CITIES[zip_code]
    if (code or "").strip() in CITY_CODES:
        return CITY_CODES[code.strip()]
    return "Las Vegas" if (zip_code or "").startswith("891") else None


def situs(client: PoliteClient, numbers: list[str]) -> dict[str, dict]:
    """City, ZIP and centroid per parcel number, from the county parcel layer."""
    found = {}
    for start in range(0, len(numbers), LOOKUP_BATCH):
        batch = numbers[start:start + LOOKUP_BATCH]
        # POST: a GET with a hundred parcel numbers is longer than the service accepts.
        response = client.post(PARCEL_LAYER, data={
            "where": "PARCEL IN ({})".format(",".join(f"'{number}'" for number in batch)),
            "outFields": "PARCEL,STRCITY,ZIPMAIN", "returnGeometry": "false", "returnCentroid": "true",
            "outSR": "4326", "f": "json"})
        response.raise_for_status()
        for feature in response.json().get("features") or []:
            row, centroid = feature["attributes"], feature.get("centroid") or {}
            zip_code = str(row.get("ZIPMAIN") or "")[:5] or None
            found[row["PARCEL"]] = {"city": city_of(row.get("STRCITY"), zip_code), "zip_code": zip_code,
                                    "latitude": centroid.get("y"), "longitude": centroid.get("x")}
    return found


def parcel_from(row: dict, places: dict[str, dict]) -> dict:
    kept = {key: row.get(key) for key in KEPT}
    street = " ".join((kept["PropertyLocation"] or "").split())
    place = places.get(apn(kept["ParcelNumber"]), {})
    return {"parcel": kept["ParcelNumber"], "minimum_bid": kept["MinBidAmount"],
            "street": None if not street or "UNASSIGNED" in street.upper() else street.title(),
            "struck": bool(kept["IsLineOut"]), "winning_bid": kept["WinningBidAmount"] or None,
            "deed_recorded": kept["DeedRecordingDate"], **place}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    with PoliteClient(ScrapingSettings.from_env()) as client:
        page = client.get(LIST_URL)
        page.raise_for_status()
        auction = auction_id(page.text)
        events = client.post(f"{BASE}/Event_Read", params={"auctionId": auction}, data=GRID)
        events.raise_for_status()
        rows = client.post(f"{BASE}/Parcel_Read", params={"auctionId": auction}, data=GRID)
        rows.raise_for_status()
        rows = rows.json()["Data"]
        places = situs(client, sorted({apn(row["ParcelNumber"]) for row in rows if row.get("ParcelNumber")}))
    if not rows:
        raise SystemExit(f"Clark County auction {auction}: no parcels listed; previous snapshot kept")
    sessions = [{"start": event["EventDateTimeStart"], "status": event["EventStatus"], "type": event["EventType"],
                 "place": re.sub(r"<[^>]+>|\s+", " ", event.get("Address") or "").strip()}
                for event in events.json()["Data"]]
    parcels = [parcel_from(row, places) for row in rows]
    snapshot = {"source_system": "nv_clark_treasurer_tax_sale", "state": "NV", "county": "Clark",
                "source_url": LIST_URL, "auction_id": auction, "sessions": sessions,
                "scraped_at": datetime.now(timezone.utc).isoformat(), "parser_version": PARSER_VERSION,
                "parcels": parcels}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, indent=1) + "\n")
    print(f"Clark County auction {auction} ({sessions[0]['start'][:10] if sessions else 'no date'}): "
          f"{len(parcels)} parcels, {sum(bool(p['street']) for p in parcels)} with a street, "
          f"{sum(bool(p.get('city')) for p in parcels if p['street'])} placed -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
