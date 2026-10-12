"""Fill missing ZIP codes (and coordinates) for properties with an upcoming sale,
using the free US Census Bureau geocoder.

Some sale lists publish no ZIP (Oklahoma County on Bid4Assets, Connecticut, ...),
and Zillow's address search rarely matches without one. A result is used only when
the Census returns exactly one match whose house number is the listing's; existing
ZIPs and coordinates are never overwritten.

    python -m pipeline.fill_missing_zips --dry-run
    python -m pipeline.fill_missing_zips --states OK CT
"""
import argparse
import json
import re
import time

import httpx
from sqlalchemy import text

from app.database.session import engine

CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/locations/address"
# City fields some sources fill with a placeholder rather than a place name.
PLACEHOLDER_CITIES = {"unincorporated", "unknown", "none", "n/a", ""}


def search_city(city):
    """The city to send the geocoder, or None when the source gave a placeholder."""
    value = (city or "").strip()
    if value.lower() in PLACEHOLDER_CITIES:
        return None
    return "The Village" if value.lower() == "village" else value


def clean_street(street):
    return re.sub(r"\s+", " ", (street or "").replace(".", " ")).strip(" ,")


def pick_match(street, matches):
    """(zip, latitude, longitude) when there is exactly one match on the same house number."""
    number = re.match(r"\d+", street or "")
    if len(matches) != 1 or not number:
        return None
    match = matches[0]
    components = match.get("addressComponents") or {}
    zip_code = (components.get("zip") or "").strip()
    if not re.fullmatch(r"\d{5}", zip_code):
        return None
    matched_number = re.match(r"\d+", match.get("matchedAddress") or "")
    if not matched_number or matched_number.group(0) != number.group(0):
        return None
    coordinates = match.get("coordinates") or {}
    return zip_code, coordinates.get("y"), coordinates.get("x")


def missing(states=None):
    with engine.connect() as connection:
        return connection.execute(text("""
            SELECT DISTINCT p.id::text AS id, p.street_address, p.city, p.state
            FROM properties p JOIN sheriff_sales ss ON ss.property_id=p.id
            WHERE strpos(lower(ss.current_status), 'scheduled') > 0
              AND COALESCE(p.zip_code, '') = '' AND p.street_address ~ '^[1-9]'
              AND (CAST(:states AS TEXT[]) IS NULL OR p.state = ANY(CAST(:states AS TEXT[])))
            ORDER BY p.state, p.street_address"""), {"states": states}).mappings().all()


def geocode(client, row):
    params = {"street": clean_street(row["street_address"]), "state": row["state"],
              "benchmark": "Public_AR_Current", "format": "json"}
    if city := search_city(row["city"]):
        params["city"] = city
    response = client.get(CENSUS_URL, params=params)
    response.raise_for_status()
    return pick_match(params["street"], response.json()["result"]["addressMatches"])


def fill(states=None, dry_run=False, pause=0.3):
    rows = missing(states)
    found, filled = [], 0
    with httpx.Client(timeout=30, headers={"User-Agent": "SheriffSaleHunter ZIP lookup"}) as client:
        for row in rows:
            try:
                result = geocode(client, row)
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                print(f"  {row['state']} {row['street_address']}: lookup failed ({type(exc).__name__})", flush=True)
                result = None
            if result:
                found.append((row, result))
            time.sleep(pause)
    if not dry_run:
        with engine.begin() as connection:
            for row, (zip_code, latitude, longitude) in found:
                filled += connection.execute(text("""UPDATE properties SET zip_code=:zip,
                    latitude=COALESCE(latitude, :latitude), longitude=COALESCE(longitude, :longitude), updated_at=NOW()
                    WHERE id=CAST(:id AS uuid) AND COALESCE(zip_code, '')=''"""),
                    {"zip": zip_code, "latitude": latitude, "longitude": longitude, "id": row["id"]}).rowcount
    by_state = {}
    for row, _ in found:
        by_state[row["state"]] = by_state.get(row["state"], 0) + 1
    return {"missing": len(rows), "matched": len(found), "filled": filled, "matched_by_state": by_state}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--states", nargs="+")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(json.dumps(fill(args.states, args.dry_run)))


if __name__ == "__main__":
    main()
