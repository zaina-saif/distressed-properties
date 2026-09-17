"""Import public Washington, DC assessment, CAMA, and property-sale records.

Only parcel, property-characteristic, assessment, and transaction fields are
requested. Owner, care-of, mailing, mortgage, and billing fields are excluded.
"""
from __future__ import annotations

import argparse
import asyncio
import re
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, AsyncIterator

import httpx
from sqlalchemy import text

from app.database.session import warehouse_engine
from pipeline.import_maryland_property_data import SALE_UPSERT, SNAPSHOT_UPSERT
from pipeline.public_property_records import (
    PropertySale,
    PropertySnapshot,
    decimal_value,
    integer_value,
    stable_hash,
    text_value,
)

COUNTY = "District of Columbia"
ASSESSMENT_SOURCE_ID = "dc_itspe_public_extract"
SALES_SOURCE_ID = "dc_cama_property_sales"
ASSESSMENT_PAGE = "https://opendata.dc.gov/datasets/7d5e6cabd2304e779c719a4d5515af77"
SALES_PAGE = "https://opendata.dc.gov/datasets/ee35b5aa5ca643679fb37c141c532a92"
ASSESSMENT_URL = (
    "https://services.arcgis.com/neT9SoYxizqTHZPH/arcgis/rest/services/"
    "ITSPE_08172026/FeatureServer/0"
)
SERVICE_ROOT = (
    "https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_DATA/"
    "Property_and_Land_WebMercator/FeatureServer"
)
SALES_URL = f"{SERVICE_ROOT}/57"
CAMA_SERVICES = {
    "Residential": (f"{SERVICE_ROOT}/25", "SSL,BEDRM,BATHRM,HF_BATHRM,AYB,GBA,LANDAREA,USECODE,GIS_LAST_MOD_DTTM,OBJECTID"),
    "Condominium": (f"{SERVICE_ROOT}/24", "SSL,BEDRM,BATHRM,HF_BATHRM,AYB,LIVING_GBA,LANDAREA,USECODE,GIS_LAST_MOD_DTTM,OBJECTID"),
    "Commercial": (f"{SERVICE_ROOT}/23", "SSL,AYB,LIVING_GBA,LANDAREA,USECODE,GIS_LAST_MOD_DTTM,OBJECTID"),
}
ASSESSMENT_FIELDS = (
    "OBJECTID,SSL,PROPTYPE,USECODE,LANDAREA,PREMISEADD,OLDLAND,OLDIMPR,OLDTOTAL,"
    "NEWLAND,NEWIMPR,NEWTOTAL,SALEPRICE,SALEDATE,DEEDDATE,EXTRACTDAT"
)
SALES_FIELDS = "OBJECTID,SSL,SALE_DATE,SALE_PRICE,QUALIFIED,SALE_CODE,GIS_LAST_MOD_DTTM"
ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\s*$")


def normalize_ssl(value: Any) -> str | None:
    value = text_value(value)
    return " ".join(value.split()) if value else None


def arcgis_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    value = text_value(value)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def arcgis_date(value: Any) -> date | None:
    parsed = arcgis_datetime(value)
    return parsed.date() if parsed else None


async def request_json(client: httpx.AsyncClient, url: str,
                       params: dict[str, Any], *, post: bool = False) -> dict[str, Any]:
    error: Exception | None = None
    for attempt in range(5):
        try:
            response = (
                await client.post(url, data=params)
                if post else await client.get(url, params=params)
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("error"):
                raise RuntimeError(str(payload["error"]))
            return payload
        except (httpx.HTTPError, ValueError, RuntimeError) as exc:
            error = exc
            if attempt < 4:
                await asyncio.sleep(2 ** attempt)
    raise RuntimeError(f"DC ArcGIS request failed after retries: {url}") from error


async def service_rows(client: httpx.AsyncClient, service_url: str,
                       fields: str, page_size: int) -> AsyncIterator[list[dict[str, Any]]]:
    id_payload = await request_json(client, f"{service_url}/query", {
        "f": "json", "where": "1=1", "returnIdsOnly": "true",
    })
    object_ids = sorted(id_payload.get("objectIds") or [])
    for start in range(0, len(object_ids), page_size):
        ids = object_ids[start:start + page_size]
        payload = await request_json(client, f"{service_url}/query", {
            "f": "json", "objectIds": ",".join(map(str, ids)),
            "outFields": fields, "returnGeometry": "false",
        }, post=True)
        yield [feature.get("attributes") or {} for feature in payload.get("features", [])]


def cama_characteristics(row: dict[str, Any], category: str) -> dict[str, Any] | None:
    ssl = normalize_ssl(row.get("SSL"))
    if not ssl:
        return None
    full_baths = decimal_value(row.get("BATHRM")) or Decimal(0)
    half_baths = decimal_value(row.get("HF_BATHRM")) or Decimal(0)
    return {
        "ssl": ssl,
        "property_type": category,
        "land_use_code": text_value(row.get("USECODE")),
        "year_built": integer_value(row.get("AYB")),
        "living_area": integer_value(row.get("GBA") or row.get("LIVING_GBA")),
        "land_area": decimal_value(row.get("LANDAREA")),
        "bedrooms": decimal_value(row.get("BEDRM")),
        "bathrooms": full_baths + half_baths / Decimal(2),
        "updated": arcgis_datetime(row.get("GIS_LAST_MOD_DTTM")),
    }


def parse_snapshot(row: dict[str, Any], cama: dict[str, Any] | None) -> PropertySnapshot | None:
    ssl = normalize_ssl(row.get("SSL"))
    extracted = arcgis_datetime(row.get("EXTRACTDAT"))
    if not ssl or not extracted:
        return None
    address = text_value(row.get("PREMISEADD"))
    zip_match = ZIP_RE.search(address or "")
    core = {
        "source_id": ASSESSMENT_SOURCE_ID,
        "state": "DC", "county": COUNTY, "source_parcel_id": ssl,
        "snapshot_year": extracted.year, "street_address": address,
        "city": "Washington", "zip_code": zip_match.group(1) if zip_match else None,
        "longitude": None, "latitude": None,
        "property_type": text_value(row.get("PROPTYPE")) or (cama or {}).get("property_type"),
        "land_use_code": text_value(row.get("USECODE")) or (cama or {}).get("land_use_code"),
        "year_built": (cama or {}).get("year_built"),
        "living_area": (cama or {}).get("living_area"),
        "land_area": decimal_value(row.get("LANDAREA")) or (cama or {}).get("land_area"),
        "land_area_unit": "square feet", "bedrooms": (cama or {}).get("bedrooms"),
        "bathrooms": (cama or {}).get("bathrooms"),
        "land_value": decimal_value(row.get("NEWLAND")),
        "improvement_value": decimal_value(row.get("NEWIMPR")),
        "total_assessed_value": decimal_value(row.get("NEWTOTAL")),
        "source_updated_at": max(filter(None, [extracted, (cama or {}).get("updated")]), default=extracted),
    }
    return PropertySnapshot(**core, source_hash=stable_hash(core))


def parse_sale(row: dict[str, Any]) -> PropertySale | None:
    ssl = normalize_ssl(row.get("SSL"))
    transaction_id = text_value(row.get("OBJECTID"))
    sale_date = arcgis_date(row.get("SALE_DATE"))
    price = decimal_value(row.get("SALE_PRICE"))
    if not ssl or not transaction_id or not sale_date or price is None or price <= 0:
        return None
    qualified = (text_value(row.get("QUALIFIED")) or "").upper()
    core = {
        "source_id": SALES_SOURCE_ID, "state": "DC", "county": COUNTY,
        "source_parcel_id": ssl, "transaction_id": transaction_id,
        "sale_date": sale_date, "recording_date": None, "sale_price": price,
        "conveyance_code": text_value(row.get("SALE_CODE")),
        "arms_length": True if qualified == "Q" else False if qualified == "U" else None,
    }
    return PropertySale(**core, source_hash=stable_hash(core))


def register_sources() -> None:
    with warehouse_engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO public_data_sources
              (source_id,state,county,source_name,source_url,access_method,coverage_notes,last_checked_at)
            VALUES
              (:assessment_id,'DC',:county,'DC Integrated Tax System Public Extract',:assessment_url,
               'arcgis_rest','Assessment roll joined to residential, condominium, and commercial CAMA characteristics; owner fields excluded',NOW()),
              (:sales_id,'DC',:county,'DC Tax System Property Sales (CAMA)',:sales_url,
               'arcgis_rest','Recorded property-sale history with qualified/unqualified indicator; owner field excluded',NOW())
            ON CONFLICT(source_id) DO UPDATE SET
              source_url=EXCLUDED.source_url,coverage_notes=EXCLUDED.coverage_notes,
              last_checked_at=NOW(),updated_at=NOW()
        """), {"assessment_id": ASSESSMENT_SOURCE_ID, "sales_id": SALES_SOURCE_ID,
                 "county": COUNTY, "assessment_url": ASSESSMENT_PAGE, "sales_url": SALES_PAGE})


async def run(page_size: int, dry_run: bool) -> None:
    characteristics: dict[str, dict[str, Any]] = {}
    snapshot_count = sale_count = 0
    headers = {"User-Agent": "nj-sheriff-sale-platform/1.0"}
    async with httpx.AsyncClient(timeout=120, headers=headers) as client:
        for category, (url, fields) in CAMA_SERVICES.items():
            seen = 0
            async for batch in service_rows(client, url, fields, page_size):
                for row in batch:
                    item = cama_characteristics(row, category)
                    if not item:
                        continue
                    current = characteristics.get(item["ssl"])
                    if current is None or (item.get("living_area") or 0) > (current.get("living_area") or 0):
                        characteristics[item["ssl"]] = item
                seen += len(batch)
                print(f"cama_{category.lower()}={seen:,} characteristics={len(characteristics):,}")

        if not dry_run:
            register_sources()
        async for batch in service_rows(client, ASSESSMENT_URL, ASSESSMENT_FIELDS, page_size):
            rows = []
            for row in batch:
                snapshot = parse_snapshot(row, characteristics.get(normalize_ssl(row.get("SSL")) or ""))
                if snapshot:
                    rows.append(snapshot.params())
            if not dry_run and rows:
                with warehouse_engine.begin() as connection:
                    connection.execute(SNAPSHOT_UPSERT, rows)
            snapshot_count += len(rows)
            print(f"dc_snapshots={snapshot_count:,}")

        async for batch in service_rows(client, SALES_URL, SALES_FIELDS, page_size):
            rows = [sale.params() for row in batch if (sale := parse_sale(row))]
            if not dry_run and rows:
                with warehouse_engine.begin() as connection:
                    connection.execute(SALE_UPSERT, rows)
            sale_count += len(rows)
            print(f"dc_sales={sale_count:,}")
    print(f"complete dry_run={dry_run} snapshots={snapshot_count:,} sales={sale_count:,}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--page-size", type=int, default=2_000)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.page_size <= 2_000:
        parser.error("--page-size must be between 1 and 2000")
    asyncio.run(run(args.page_size, args.dry_run))


if __name__ == "__main__":
    main()
