"""City and ZIP for Colorado street-only sale addresses.

Colorado Public Trustee sites often list a street with no city or ZIP. The
state's public address points (Colorado_Public_Addresses, aggregated by OIT
from county and municipal data) give the city ("PlaceName") and ZIP for a
house number and street in a county. A result is used only when the match is
unambiguous; otherwise the sale stays without a city and is not loaded.
"""
from __future__ import annotations

import re
from functools import lru_cache

import httpx

ADDRESSES = ("https://gis.colorado.gov/public/rest/services/Address_and_Parcel/"
             "Colorado_Public_Addresses/FeatureServer/0/query")
DIRECTIONS = {"N", "S", "E", "W", "NE", "NW", "SE", "SW", "NORTH", "SOUTH", "EAST", "WEST"}
SOURCE = "Colorado Public Addresses (gis.colorado.gov)"


def street_key(street: str) -> tuple[str, str] | None:
    """House number and first street-name word: "1261 W 71st Pl" -> ("1261", "71ST")."""
    tokens = re.sub(r"[^A-Za-z0-9/ ]", " ", street).upper().split()
    if len(tokens) < 2 or not re.fullmatch(r"\d+", tokens[0]):
        return None
    rest = tokens[1:]
    if rest[0] in DIRECTIONS and len(rest) > 1:
        rest = rest[1:]
    if rest[0].endswith("/2") or rest[0] == "1/2":  # "2703 1/2 RINCON DR"
        rest = rest[1:] or rest
    return tokens[0], rest[0]


def choose(features: list[dict]) -> tuple[str, str] | None:
    """The single (city, ZIP) the matches agree on, else None."""
    places = {(f["attributes"].get("PlaceName"), f["attributes"].get("Zipcode")) for f in features}
    places = {(city.strip().title(), zip_code[:5]) for city, zip_code in places if city and zip_code}
    return places.pop() if len(places) == 1 else None


@lru_cache(maxsize=4096)
def city_and_zip(street: str, county: str) -> tuple[str, str] | None:
    key = street_key(street)
    if key is None:
        return None
    number, name = key
    where = (f"AddrNum='{number}' AND UPPER(StreetName) LIKE '{name.replace(chr(39), '')}%' "
             f"AND UPPER(County) LIKE '{county.upper().replace(chr(39), '')}%'")
    try:
        response = httpx.get(ADDRESSES, timeout=30, params={
            "where": where, "outFields": "PlaceName,Zipcode", "returnGeometry": "false", "f": "json"})
        response.raise_for_status()
        return choose(response.json().get("features", []))
    except (httpx.HTTPError, ValueError):
        return None
