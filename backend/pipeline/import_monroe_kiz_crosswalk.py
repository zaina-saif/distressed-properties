"""Import Monroe County's public KIZ parcel crosswalk and assessment subset."""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import httpx
from sqlalchemy import text

from pipeline.pa_parcel_numbers import normalize_map_number


LAYER_URL = (
    "https://services6.arcgis.com/AISpg3PNp6bMI13R/arcgis/rest/services/"
    "KIZ_Parcels/FeatureServer/0"
)
QUERY_URL = f"{LAYER_URL}/query"
MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "016_monroe_property_details.sql"
FIELDS = (
    "FID,MAPNUMBER,PARID,OWNER,IAS_TAXYEA,BLDGVALUE,PREFVALUE,LANDVALUE,CLASS,"
    "LANDUSE,ACREAGE,LOCATION,SALEDATE,SALEAMT"
)


def parse_sale_date(value: object):
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    try:
        return datetime.strptime(cleaned, "%m/%d/%Y").date()
    except ValueError:
        return None


def assessment_row(attributes: dict) -> dict | None:
    map_number = str(attributes.get("MAPNUMBER") or "").strip()
    tax_parcel_id = str(attributes.get("PARID") or "").strip()
    if not map_number or not tax_parcel_id:
        return None
    land = attributes.get("LANDVALUE")
    improvement = attributes.get("BLDGVALUE")
    preferential = attributes.get("PREFVALUE")
    assessed_parts = [value for value in (land, improvement, preferential) if value is not None]
    return {
        "map_number": map_number,
        "tax_parcel_id": tax_parcel_id,
        "normalized_tax_parcel_id": normalize_map_number(tax_parcel_id),
        "owner_name": str(attributes.get("OWNER") or "").strip() or None,
        "assessed_value": sum(assessed_parts) if assessed_parts else None,
        "land_value": land,
        "improvement_value": improvement,
        "preferential_value": preferential,
        "property_type": str(attributes.get("CLASS") or "").strip() or None,
        "land_use_code": str(attributes.get("LANDUSE") or "").strip() or None,
        "acreage": attributes.get("ACREAGE"),
        "property_location": str(attributes.get("LOCATION") or "").strip() or None,
        "last_sale_date": parse_sale_date(attributes.get("SALEDATE")),
        "last_sale_price": attributes.get("SALEAMT"),
        "assessment_year": int(attributes["IAS_TAXYEA"]) if attributes.get("IAS_TAXYEA") else None,
        "source_object_id": attributes.get("FID"),
        "raw_payload": json.dumps(attributes, default=str),
    }


def apply_migration() -> None:
    from app.database.session import engine
    with engine.begin() as connection:
        connection.execute(text(MIGRATION.read_text()))


def import_crosswalk() -> dict[str, int]:
    from app.database.session import engine
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        metadata = client.get(LAYER_URL, params={"f": "json"}).json()
        available = {field["name"] for field in metadata.get("fields", [])}
        required = {"FID", "MAPNUMBER", "PARID"}
        if not required <= available:
            raise RuntimeError(f"KIZ schema changed; missing {sorted(required - available)}")
        page_size = min(int(metadata.get("maxRecordCount") or 2000), 2000)
        expected = int(client.get(QUERY_URL, params={
            "where": "1=1", "returnCountOnly": "true", "f": "json",
        }).json()["count"])
        rows: list[dict] = []
        skipped = 0
        for offset in range(0, expected, page_size):
            response = client.get(QUERY_URL, params={
                "where": "1=1", "outFields": FIELDS, "returnGeometry": "false",
                "resultOffset": offset, "resultRecordCount": page_size,
                "orderByFields": "FID", "f": "json",
            })
            response.raise_for_status()
            payload = response.json()
            if payload.get("error"):
                raise RuntimeError(payload["error"])
            for feature in payload.get("features", []):
                row = assessment_row(feature.get("attributes") or {})
                if row is None:
                    skipped += 1
                else:
                    rows.append(row)

    with engine.begin() as connection:
        parcel_ids = {
            item["map_number"]: item["id"]
            for item in connection.execute(text("""SELECT id,map_number FROM pa_parcels
              WHERE state='PA' AND county='Monroe' AND map_number=ANY(:map_numbers)"""),
              {"map_numbers": [row["map_number"] for row in rows]}).mappings()
        }
        matched_rows = [
            {**row, "parcel_id": parcel_ids[row["map_number"]], "source": LAYER_URL}
            for row in rows if row["map_number"] in parcel_ids
        ]
        matched_ids = [row["parcel_id"] for row in matched_rows]
        updated = int(connection.execute(text("""SELECT COUNT(*) FROM pa_property_details
          WHERE parcel_id=ANY(:parcel_ids)"""), {"parcel_ids": matched_ids}).scalar_one())
        inserted = len(matched_rows) - updated
        if matched_rows:
            connection.execute(text("""UPDATE pa_parcels SET tax_parcel_id=:tax_parcel_id,
              normalized_tax_parcel_id=:normalized_tax_parcel_id,updated_at=NOW()
              WHERE id=:parcel_id"""), matched_rows)
            connection.execute(text("""INSERT INTO pa_property_details(parcel_id,map_number,
              tax_parcel_id,normalized_tax_parcel_id,owner_name,assessed_value,land_value,
              improvement_value,preferential_value,property_type,land_use_code,acreage,property_location,
              last_sale_date,last_sale_price,assessment_year,enrichment_source,source_object_id,raw_payload)
              VALUES(:parcel_id,:map_number,:tax_parcel_id,:normalized_tax_parcel_id,:owner_name,
              :assessed_value,:land_value,:improvement_value,:preferential_value,:property_type,
              :land_use_code,:acreage,:property_location,:last_sale_date,:last_sale_price,:assessment_year,
              :source,:source_object_id,CAST(:raw_payload AS JSONB))
              ON CONFLICT(parcel_id) DO UPDATE SET tax_parcel_id=EXCLUDED.tax_parcel_id,
              normalized_tax_parcel_id=EXCLUDED.normalized_tax_parcel_id,
              owner_name=EXCLUDED.owner_name,assessed_value=EXCLUDED.assessed_value,
              land_value=EXCLUDED.land_value,improvement_value=EXCLUDED.improvement_value,
              preferential_value=EXCLUDED.preferential_value,property_type=EXCLUDED.property_type,
              land_use_code=EXCLUDED.land_use_code,
              acreage=EXCLUDED.acreage,property_location=EXCLUDED.property_location,
              last_sale_date=EXCLUDED.last_sale_date,last_sale_price=EXCLUDED.last_sale_price,
              assessment_year=EXCLUDED.assessment_year,enrichment_source=EXCLUDED.enrichment_source,
              source_object_id=EXCLUDED.source_object_id,raw_payload=EXCLUDED.raw_payload,updated_at=NOW()"""),
              matched_rows)
    return {"expected": expected, "parsed": len(rows), "matched_to_pasda": len(matched_rows),
            "inserted": inserted, "updated": updated, "skipped": skipped,
            "unmatched_to_pasda": len(rows) - len(matched_rows)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply-migration", action="store_true")
    args = parser.parse_args()
    if args.apply_migration:
        apply_migration()
        print("Migration 016 applied")
    print("Monroe KIZ crosswalk import complete:", import_crosswalk())


if __name__ == "__main__":
    main()
