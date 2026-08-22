"""Import Monroe County parcel geometry from the public PASDA ArcGIS service."""
from __future__ import annotations

import argparse
import csv
import io
import json
from decimal import Decimal
from pathlib import Path
from typing import Iterable

import httpx

from pipeline.pa_parcel_numbers import normalize_map_number


SERVICE_URL = (
    "https://imagery.pasda.psu.edu/arcgis/rest/services/"
    "pasda/MonroeCounty/MapServer/1"
)
QUERY_URL = f"{SERVICE_URL}/query"
SOURCE_LAYER = "Monroe County Parcels 202203"
MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "014_pa_parcels.sql"


def polygon_centroid(geometry: dict) -> tuple[float | None, float | None]:
    """Return (latitude, longitude) using area-weighted exterior-ring centroids."""
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    if geometry_type == "Polygon":
        rings = [coordinates[0]] if coordinates else []
    elif geometry_type == "MultiPolygon":
        rings = [polygon[0] for polygon in coordinates if polygon]
    else:
        return None, None

    weighted_x = weighted_y = total_area = 0.0
    fallback: list[tuple[float, float]] = []
    for ring in rings:
        if len(ring) < 3:
            continue
        fallback.extend((float(point[0]), float(point[1])) for point in ring)
        twice_area = centroid_x = centroid_y = 0.0
        for first, second in zip(ring, ring[1:] + ring[:1]):
            cross = float(first[0]) * float(second[1]) - float(second[0]) * float(first[1])
            twice_area += cross
            centroid_x += (float(first[0]) + float(second[0])) * cross
            centroid_y += (float(first[1]) + float(second[1])) * cross
        if abs(twice_area) < 1e-12:
            continue
        area = abs(twice_area) / 2
        weighted_x += (centroid_x / (3 * twice_area)) * area
        weighted_y += (centroid_y / (3 * twice_area)) * area
        total_area += area

    if total_area:
        return weighted_y / total_area, weighted_x / total_area
    if fallback:
        return (
            sum(point[1] for point in fallback) / len(fallback),
            sum(point[0] for point in fallback) / len(fallback),
        )
    return None, None


def validate_metadata(metadata: dict) -> tuple[str, int]:
    fields = {field["name"]: field for field in metadata.get("fields", [])}
    if "OBJECTID" not in fields or "MAPNUMBER" not in fields:
        raise RuntimeError(f"PASDA schema changed; available fields: {sorted(fields)}")
    if not metadata.get("advancedQueryCapabilities", {}).get("supportsPagination"):
        raise RuntimeError("PASDA layer does not report pagination support")
    formats = {item.strip().lower() for item in metadata.get("supportedQueryFormats", "").split(",")}
    if "geojson" not in formats:
        raise RuntimeError("PASDA layer does not report GeoJSON support")
    return "OBJECTID", min(int(metadata.get("maxRecordCount") or 2000), 2000)


def feature_rows(features: Iterable[dict]) -> list[dict]:
    rows: list[dict] = []
    for feature in features:
        properties = feature.get("properties") or {}
        map_number = str(properties.get("MAPNUMBER") or "").strip()
        normalized = normalize_map_number(map_number)
        geometry = feature.get("geometry")
        object_id = properties.get("OBJECTID")
        if not normalized or geometry is None or object_id is None:
            continue
        latitude, longitude = polygon_centroid(geometry)
        rows.append({
            "map_number": map_number,
            "normalized_map_number": normalized,
            "source_object_id": int(object_id),
            "geometry": json.dumps(geometry, separators=(",", ":")),
            "latitude": Decimal(str(round(latitude, 7))) if latitude is not None else None,
            "longitude": Decimal(str(round(longitude, 7))) if longitude is not None else None,
        })
    return rows


def deduplicate_rows(rows: list[dict]) -> tuple[list[dict], int]:
    """Keep one deterministic source feature per normalized parcel identifier."""
    by_map_number: dict[str, dict] = {}
    for row in rows:
        key = row["normalized_map_number"]
        existing = by_map_number.get(key)
        if existing is None or row["source_object_id"] > existing["source_object_id"]:
            by_map_number[key] = row
    unique_rows = sorted(by_map_number.values(), key=lambda row: row["source_object_id"])
    return unique_rows, len(rows) - len(unique_rows)


def save_batch(connection, rows: list[dict]) -> tuple[int, int, int]:
    if not rows:
        return 0, 0, 0
    rows, duplicate_count = deduplicate_rows(rows)
    stream = io.StringIO()
    writer = csv.writer(stream, lineterminator="\n")
    for row in rows:
        writer.writerow([
            row["map_number"], row["normalized_map_number"], row["source_object_id"],
            row["geometry"], row["latitude"] if row["latitude"] is not None else "\\N",
            row["longitude"] if row["longitude"] is not None else "\\N",
        ])
    stream.seek(0)
    with connection.cursor() as cursor:
        cursor.execute("""CREATE TEMP TABLE IF NOT EXISTS monroe_pasda_stage(
          map_number TEXT,normalized_map_number TEXT,source_object_id BIGINT,
          geometry JSONB,latitude NUMERIC,longitude NUMERIC) ON COMMIT PRESERVE ROWS""")
        cursor.execute("TRUNCATE monroe_pasda_stage")
        cursor.copy_expert("""COPY monroe_pasda_stage(map_number,normalized_map_number,
          source_object_id,geometry,latitude,longitude) FROM STDIN WITH(FORMAT CSV,NULL '\\N')""", stream)
        cursor.execute("""SELECT COUNT(*) FROM monroe_pasda_stage s WHERE NOT EXISTS(
          SELECT 1 FROM pa_parcels p WHERE p.state='PA' AND p.county='Monroe'
          AND p.normalized_map_number=s.normalized_map_number)""")
        inserted = int(cursor.fetchone()[0])
        updated = len(rows) - inserted
        cursor.execute("""INSERT INTO pa_parcels(state,county,map_number,normalized_map_number,
          source_object_id,geometry,latitude,longitude,source,source_layer)
          SELECT 'PA','Monroe',map_number,normalized_map_number,source_object_id,geometry,
            latitude,longitude,%s,%s FROM monroe_pasda_stage
          ON CONFLICT(state,county,normalized_map_number) DO UPDATE SET
            map_number=EXCLUDED.map_number,source_object_id=EXCLUDED.source_object_id,
            geometry=EXCLUDED.geometry,latitude=EXCLUDED.latitude,longitude=EXCLUDED.longitude,
            source=EXCLUDED.source,source_layer=EXCLUDED.source_layer,updated_at=NOW()""",
          (SERVICE_URL, SOURCE_LAYER))
    connection.commit()
    return inserted, updated, duplicate_count


def apply_migration() -> None:
    from app.database.session import engine
    connection = engine.raw_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(MIGRATION.read_text())
        connection.commit()
    finally:
        connection.close()


def import_parcels(page_size: int | None = None) -> dict[str, int]:
    from app.database.session import engine
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        metadata = client.get(SERVICE_URL, params={"f": "json"}).json()
        _, service_page_size = validate_metadata(metadata)
        page_size = min(page_size or service_page_size, service_page_size)
        count_payload = client.get(QUERY_URL, params={
            "where": "1=1", "returnCountOnly": "true", "f": "json",
        }).json()
        expected = int(count_payload["count"])
        connection = engine.raw_connection()
        downloaded = inserted = updated = skipped = errors = 0
        seen_map_numbers: set[str] = set()
        try:
            for offset in range(0, expected, page_size):
                response = client.get(QUERY_URL, params={
                    "where": "1=1", "outFields": "OBJECTID,MAPNUMBER",
                    "returnGeometry": "true", "outSR": "4326",
                    "resultOffset": offset, "resultRecordCount": page_size,
                    "orderByFields": "OBJECTID", "f": "geojson",
                })
                response.raise_for_status()
                payload = response.json()
                if payload.get("error"):
                    raise RuntimeError(payload["error"])
                features = payload.get("features", [])
                downloaded += len(features)
                rows = feature_rows(features)
                skipped += len(features) - len(rows)
                rows, batch_duplicates = deduplicate_rows(rows)
                skipped += batch_duplicates
                new_rows = [
                    row for row in rows
                    if row["normalized_map_number"] not in seen_map_numbers
                ]
                skipped += len(rows) - len(new_rows)
                seen_map_numbers.update(row["normalized_map_number"] for row in new_rows)
                try:
                    batch_inserted, batch_updated, _ = save_batch(connection, new_rows)
                    inserted += batch_inserted
                    updated += batch_updated
                except Exception:
                    connection.rollback()
                    errors += len(new_rows)
                    raise
                print(
                    f"PASDA parcels: {downloaded}/{expected} downloaded; "
                    f"{inserted} inserted; {updated} updated; {skipped} skipped"
                )
        finally:
            connection.close()
    return {"expected": expected, "downloaded": downloaded, "inserted": inserted,
            "updated": updated, "skipped": skipped, "errors": errors}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply-migration", action="store_true")
    parser.add_argument("--page-size", type=int)
    args = parser.parse_args()
    if args.apply_migration:
        apply_migration()
        print("Migration 014 applied")
    stats = import_parcels(args.page_size)
    print("Monroe PASDA import complete:", stats)


if __name__ == "__main__":
    main()
