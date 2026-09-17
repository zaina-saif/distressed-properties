"""Import Ohio OGRIP's public statewide parcel view into the warehouse.

Owner and mailing fields are never requested. The public statewide view does
not expose valuation or sale-history fields; those need county-source adapters.
"""
from __future__ import annotations

import argparse
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Iterator

import httpx
from psycopg2.extras import execute_values
from sqlalchemy import text

from app.database.session import warehouse_engine
from pipeline.public_property_records import decimal_value, stable_hash, text_value

SOURCE_ID = "oh_ogrip_parcels_2026"
SOURCE_PAGE = "https://ohioparcels-geohio.hub.arcgis.com/"
LAYER_URL = ("https://services2.arcgis.com/MlJ0G8iWUyC7jAmu/ArcGIS/rest/services/"
             "OhioStatewidePacels_full_view/FeatureServer/0")
SNAPSHOT_YEAR = 2026
# The public view enforces a 2,000-row transfer limit even though its metadata
# advertises a larger no-geometry standard limit.
PAGE_SIZE = 2_000
FIELDS = "OBJECTID,County,LocalParcelID,StateParcelID,StateLUC,SitusAddressAll,LandArea,CurrentTo"
SNAPSHOT_COLUMNS = (
    "source_id", "state", "county", "source_parcel_id", "snapshot_year",
    "street_address", "property_type", "land_use_code", "land_area",
    "land_area_unit", "source_hash",
)
SNAPSHOT_SQL = f"""
INSERT INTO public_property_snapshots ({','.join(SNAPSHOT_COLUMNS)}) VALUES %s
ON CONFLICT (source_id,source_parcel_id,snapshot_year) DO UPDATE SET
 county=EXCLUDED.county,street_address=EXCLUDED.street_address,
 property_type=EXCLUDED.property_type,land_use_code=EXCLUDED.land_use_code,
 land_area=EXCLUDED.land_area,land_area_unit=EXCLUDED.land_area_unit,
 source_hash=EXCLUDED.source_hash,imported_at=NOW()
WHERE public_property_snapshots.source_hash <> EXCLUDED.source_hash
"""


def request_json(client: httpx.Client, url: str, params: dict[str, Any]) -> dict[str, Any]:
    for attempt in range(10):
        try:
            # ArcGIS query endpoints accept form POSTs. This avoids HTTP 414
            # when an object-ID batch would make a GET URL too long.
            response = client.post(url, data=params)
            response.raise_for_status()
            payload = response.json()
            if "error" in payload:
                raise RuntimeError(str(payload["error"]))
            return payload
        except (httpx.HTTPError, RuntimeError):
            if attempt == 9:
                raise
            time.sleep(min(2 ** attempt, 60))
    raise AssertionError("unreachable")


def discover_counties(client: httpx.Client) -> list[str]:
    payload = request_json(client, f"{LAYER_URL}/query", {
        "where": "1=1", "outFields": "County", "returnGeometry": "false",
        "returnDistinctValues": "true", "orderByFields": "County", "f": "json",
    })
    counties = [text_value(feature["attributes"].get("County")) for feature in payload["features"]]
    result = [county for county in counties if county]
    if len(result) != 88:
        raise RuntimeError(f"Expected 88 Ohio counties, found {len(result)}")
    return result


def county_rows(client: httpx.Client, county: str) -> Iterator[dict[str, Any]]:
    escaped = county.replace("'", "''")
    identity_payload = request_json(client, f"{LAYER_URL}/query", {
        "where": f"County='{escaped}'", "returnIdsOnly": "true", "f": "json",
    })
    object_ids = sorted(identity_payload.get("objectIds") or [])
    for start in range(0, len(object_ids), PAGE_SIZE):
        page_ids = object_ids[start:start + PAGE_SIZE]
        payload = request_json(client, f"{LAYER_URL}/query", {
            # Explicit object-ID batches avoid ArcGIS's undocumented offset and
            # filtered-tail limits on the two largest county views.
            "objectIds": ",".join(str(value) for value in page_ids),
            "outFields": FIELDS, "returnGeometry": "false",
            "orderByFields": "OBJECTID", "f": "json",
        })
        features = payload.get("features", [])
        if len(features) != len(page_ids):
            raise RuntimeError(
                f"Expected {len(page_ids)} Ohio {county} features, received {len(features)}"
            )
        for feature in features:
            yield feature["attributes"]


def parse_parcel(row: dict[str, Any]) -> tuple[Any, ...] | None:
    county = text_value(row.get("County"))
    local_id = text_value(row.get("LocalParcelID"))
    parcel_id = text_value(row.get("StateParcelID"))
    if not parcel_id and county and local_id:
        parcel_id = f"{county}:{local_id}"
    if not county or not parcel_id:
        return None
    land_use = text_value(row.get("StateLUC"))
    land_area = decimal_value(row.get("LandArea"))
    if land_area is not None and land_area <= 0:
        land_area = None
    core = {
        "source_id": SOURCE_ID, "state": "OH", "county": county,
        "source_parcel_id": parcel_id, "snapshot_year": SNAPSHOT_YEAR,
        "street_address": text_value(row.get("SitusAddressAll")),
        "property_type": land_use, "land_use_code": land_use,
        "land_area": land_area,
        "land_area_unit": "source units" if land_area is not None else None,
    }
    return tuple(core[name] for name in SNAPSHOT_COLUMNS[:-1]) + (stable_hash(core),)


def completed_counties() -> set[str]:
    with warehouse_engine.connect() as connection:
        return set(connection.execute(text("""
            SELECT file_name FROM public_import_files
            WHERE source_id=:source_id AND status='completed'
        """), {"source_id": SOURCE_ID}).scalars())


def register_source() -> None:
    with warehouse_engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO public_data_sources
              (source_id,state,source_name,source_url,access_method,coverage_notes,last_checked_at)
            VALUES (:id,'OH','Ohio OGRIP Statewide Parcels',:url,'arcgis_rest',
              'All 88 counties; parcel identity, situs address, land use and land area; owner and mailing fields excluded',NOW())
            ON CONFLICT(source_id) DO UPDATE SET last_checked_at=NOW(),updated_at=NOW()
        """), {"id": SOURCE_ID, "url": SOURCE_PAGE})


def import_county(client: httpx.Client, county: str, batch_size: int, dry_run: bool) -> int:
    seen = loaded = 0
    connection = warehouse_engine.raw_connection() if not dry_run else None
    try:
        cursor = connection.cursor() if connection else None
        batch: dict[str, tuple[Any, ...]] = {}
        for row in county_rows(client, county):
            seen += 1
            parsed = parse_parcel(row)
            if parsed is not None:
                batch[parsed[3]] = parsed
            if len(batch) >= batch_size:
                if cursor:
                    execute_values(cursor, SNAPSHOT_SQL, list(batch.values()), page_size=batch_size)
                    connection.commit()
                loaded += len(batch); batch.clear()
                print(f"Ohio {county}: source={seen:,} loaded={loaded:,}", flush=True)
        if batch:
            if cursor:
                execute_values(cursor, SNAPSHOT_SQL, list(batch.values()), page_size=batch_size)
                connection.commit()
            loaded += len(batch)
        if connection:
            with connection.cursor() as manifest:
                manifest.execute("""
                    INSERT INTO public_import_files
                      (source_id,file_name,file_url,row_count,status,completed_at)
                    VALUES(%s,%s,%s,%s,'completed',NOW())
                    ON CONFLICT(source_id,file_name) DO UPDATE SET
                      file_url=EXCLUDED.file_url,row_count=EXCLUDED.row_count,
                      status='completed',completed_at=NOW()
                """, (SOURCE_ID, county, LAYER_URL, loaded))
            connection.commit()
    finally:
        if connection:
            connection.close()
    print(f"complete Ohio {county}: source={seen:,} loaded={loaded:,}", flush=True)
    return loaded


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--county", help="Import one county only")
    parser.add_argument("--batch-size", type=int, default=5_000)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    with httpx.Client(timeout=120, follow_redirects=True,
                      headers={"User-Agent": "NJ-Sheriff-Sale-Public-Data/1.0"}) as client:
        counties = discover_counties(client)
        if args.county:
            counties = [county for county in counties if county.casefold() == args.county.casefold()]
            if not counties:
                raise SystemExit(f"Unknown Ohio county: {args.county}")
        if not args.dry_run:
            register_source()
        done = completed_counties() if not args.dry_run else set()
        pending = []
        for position, county in enumerate(counties, 1):
            if county in done:
                print(f"skip completed Ohio {county}", flush=True)
                continue
            print(f"start Ohio county={position}/{len(counties)} name={county}", flush=True)
            pending.append(county)

    def run(county: str) -> int:
        with httpx.Client(timeout=120, follow_redirects=True,
                          headers={"User-Agent": "NJ-Sheriff-Sale-Public-Data/1.0"}) as worker_client:
            return import_county(worker_client, county, args.batch_size, args.dry_run)

    if args.workers <= 1:
        for county in pending:
            run(county)
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            list(executor.map(run, pending))


if __name__ == "__main__":
    main()
