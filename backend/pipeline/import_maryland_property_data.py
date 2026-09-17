"""Import statewide Maryland SDAT/MDP assessments and three sale segments.

Only selected AVM fields are requested from Socrata. Owner and grantor names are
deliberately excluded, reducing storage and avoiding unnecessary personal data.
"""
from __future__ import annotations

import argparse
import asyncio
import re
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
from sqlalchemy import text

from app.database.session import warehouse_engine
from pipeline.public_property_records import (
    PropertySale,
    PropertySnapshot,
    date_value,
    decimal_value,
    integer_value,
    source_timestamp,
    stable_hash,
    text_value,
)

SOURCE_ID = "md_sdat_mdp_statewide"
SOURCE_URL = "https://opendata.maryland.gov/resource/ed4q-f8tm.json"
SOURCE_PAGE = "https://opendata.maryland.gov/d/ed4q-f8tm"
MIGRATION = Path(__file__).resolve().parents[1] / "migrations/019_public_avm_history.sql"
PAGE_SIZE = 10_000

FIELDS = {
    "county": "county_name_mdp_field_cntyname",
    "parcel": "account_id_mdp_field_acctid",
    "longitude": "mdp_longitude_mdp_field_digxcord_converted_to_wgs84",
    "latitude": "mdp_latitude_mdp_field_digycord_converted_to_wgs84",
    "address": "mdp_street_address_mdp_field_address",
    "city": "mdp_street_address_city_mdp_field_city",
    "zip": "mdp_street_address_zip_code_mdp_field_zipcode",
    "premise_number": "premise_address_number_mdp_field_premsnum_sdat_field_20",
    "premise_suffix": "premise_address_number_suffix_sdat_field_21",
    "premise_direction": "premise_address_direction_mdp_field_premsdir_sdat_field_22",
    "premise_name": "premise_address_name_mdp_field_premsnam_sdat_field_23",
    "premise_type": "premise_address_type_mdp_field_premstyp_sdat_field_24",
    "premise_city": "premise_address_city_mdp_field_premcity_sdat_field_25",
    "premise_zip": "premise_address_zip_code_mdp_field_premzip_sdat_field_26",
    "land_use": "land_use_code_mdp_field_lu_desclu_sdat_field_50",
    "year_built": "c_a_m_a_system_data_year_built_yyyy_mdp_field_yearblt_sdat_field_235",
    "living_area": "c_a_m_a_system_data_structure_area_sq_ft_mdp_field_sqftstrc_sdat_field_241",
    "land_area": "c_a_m_a_system_data_land_area_mdp_field_landarea_sdat_field_242",
    "land_unit": "c_a_m_a_system_data_land_unit_of_measure_mdp_field_luom_sdat_field_243",
    "tax_year": "tax_roll_values_tax_year_as_of_july_1_sdat_field_246",
    "land_value": "current_cycle_data_land_value_mdp_field_names_nfmlndvl_curlndvl_and_sallndvl_sdat_field_164",
    "improvement_value": "current_cycle_data_improvements_value_mdp_field_names_nfmimpvl_curimpvl_and_salimpvl_sdat_field_165",
    "assessed": "current_assessment_year_total_assessment_sdat_field_172",
    "updated": "date_of_most_recent_open_data_portal_record_update",
}
for segment, base in ((1, 79), (2, 99), (3, 119)):
    prefix = f"sales_segment_{segment}"
    suffix = "_mdp_field_transno1" if segment == 1 else ""
    FIELDS[f"sale_{segment}_id"] = f"{prefix}_transfer_number{suffix}_sdat_field_{base}"
    date_suffix = "_mdp_field_tradate" if segment == 1 else ""
    FIELDS[f"sale_{segment}_date"] = f"{prefix}_transfer_date_yyyy_mm_dd{date_suffix}_sdat_field_{base + 10}"
    consideration_suffix = "_mdp_field_considr1" if segment == 1 else ""
    FIELDS[f"sale_{segment}_price"] = f"{prefix}_consideration{consideration_suffix}_sdat_field_{base + 11}"
    convey_suffix = "_mdp_field_convey1" if segment == 1 else ""
    FIELDS[f"sale_{segment}_conveyance"] = f"{prefix}_how_conveyed_ind{convey_suffix}_sdat_field_{base + 8}"


def premise_number(value: Any) -> str | None:
    raw = text_value(value)
    if not raw or not re.fullmatch(r"0*\d+[A-Za-z]?", raw):
        return None
    normalized = raw.lstrip("0")
    return normalized if normalized and normalized[0].isdigit() else None


def address_parts(row: dict[str, Any]) -> tuple[str | None, str | None, str | None, bool]:
    combined = text_value(row.get(FIELDS["address"]))
    city = text_value(row.get(FIELDS["city"])) or text_value(row.get(FIELDS["premise_city"]))
    premise_zip = text_value(row.get(FIELDS["premise_zip"]))
    if premise_zip == "00000":
        premise_zip = None
    zip_code = text_value(row.get(FIELDS["zip"])) or premise_zip
    if combined:
        return combined, city, zip_code, re.match(r"^\d", combined) is None
    name = text_value(row.get(FIELDS["premise_name"]))
    if not name:
        return None, city, zip_code, False
    number = premise_number(row.get(FIELDS["premise_number"]))
    address = " ".join(filter(None, (
        number, text_value(row.get(FIELDS["premise_suffix"])) if number else None,
        text_value(row.get(FIELDS["premise_direction"])), name,
        text_value(row.get(FIELDS["premise_type"])),
    )))
    return address, city, zip_code, not bool(number)


def parse_row(row: dict[str, Any]) -> tuple[PropertySnapshot | None, list[PropertySale]]:
    parcel = text_value(row.get(FIELDS["parcel"]))
    county = text_value(row.get(FIELDS["county"]))
    year = integer_value(row.get(FIELDS["tax_year"]))
    updated = source_timestamp(row.get(FIELDS["updated"]))
    if not year or not 1900 <= year <= 2100:
        year = updated.year if updated else None
    if not parcel or not county or not year:
        return None, []
    address, city, zip_code, house_number_unavailable = address_parts(row)
    core = {
        "source_id": SOURCE_ID, "state": "MD", "county": county,
        "source_parcel_id": parcel, "snapshot_year": year,
        "street_address": address,
        "city": city,
        "zip_code": zip_code,
        "house_number_unavailable": house_number_unavailable,
        "longitude": decimal_value(row.get(FIELDS["longitude"])),
        "latitude": decimal_value(row.get(FIELDS["latitude"])),
        "property_type": text_value(row.get(FIELDS["land_use"])),
        "land_use_code": text_value(row.get(FIELDS["land_use"])),
        "year_built": integer_value(row.get(FIELDS["year_built"])),
        "living_area": integer_value(row.get(FIELDS["living_area"])),
        "land_area": decimal_value(row.get(FIELDS["land_area"])),
        "land_area_unit": text_value(row.get(FIELDS["land_unit"])),
        "land_value": decimal_value(row.get(FIELDS["land_value"])),
        "improvement_value": decimal_value(row.get(FIELDS["improvement_value"])),
        "total_assessed_value": decimal_value(row.get(FIELDS["assessed"])),
        "source_updated_at": updated,
    }
    snapshot = PropertySnapshot(**core, source_hash=stable_hash(core))
    sales: list[PropertySale] = []
    for segment in range(1, 4):
        transaction = text_value(row.get(FIELDS[f"sale_{segment}_id"]))
        sale_date = date_value(row.get(FIELDS[f"sale_{segment}_date"]))
        price = decimal_value(row.get(FIELDS[f"sale_{segment}_price"]))
        if not transaction or not sale_date or price is None or price <= 0:
            continue
        sale_core = {
            "source_id": SOURCE_ID, "state": "MD", "county": county,
            "source_parcel_id": parcel, "transaction_id": transaction,
            "sale_date": sale_date, "sale_price": price,
            "conveyance_code": text_value(row.get(FIELDS[f"sale_{segment}_conveyance"])),
        }
        sales.append(PropertySale(**sale_core, source_hash=stable_hash(sale_core)))
    return snapshot, sales


async def pages(client: httpx.AsyncClient, county: str | None,
                limit: int | None, start_offset: int = 0,
                page_size: int = PAGE_SIZE) -> AsyncIterator[list[dict[str, Any]]]:
    offset = start_offset
    end_offset = start_offset + limit if limit is not None else None
    while end_offset is None or offset < end_offset:
        size = min(page_size, end_offset - offset) if end_offset is not None else page_size
        params = {"$select": ",".join(FIELDS.values()), "$limit": size,
                  "$offset": offset, "$order": FIELDS["parcel"]}
        if county:
            escaped = county.replace("'", "''")
            params["$where"] = f"{FIELDS['county']}='{escaped}'"
        response = await client.get(SOURCE_URL, params=params)
        response.raise_for_status()
        rows = response.json()
        if not rows:
            break
        yield rows
        offset += len(rows)
        if len(rows) < size:
            break


SNAPSHOT_UPSERT = text("""
INSERT INTO public_property_snapshots
  (source_id,state,county,source_parcel_id,snapshot_year,street_address,city,zip_code,
   longitude,latitude,property_type,land_use_code,year_built,living_area,land_area,
   land_area_unit,bedrooms,bathrooms,land_value,improvement_value,total_assessed_value,
   source_updated_at,house_number_unavailable,source_hash)
VALUES
  (:source_id,:state,:county,:source_parcel_id,:snapshot_year,:street_address,:city,:zip_code,
   :longitude,:latitude,:property_type,:land_use_code,:year_built,:living_area,:land_area,
   :land_area_unit,:bedrooms,:bathrooms,:land_value,:improvement_value,:total_assessed_value,
   :source_updated_at,:house_number_unavailable,:source_hash)
ON CONFLICT (source_id,source_parcel_id,snapshot_year) DO UPDATE SET
  county=EXCLUDED.county,street_address=EXCLUDED.street_address,city=EXCLUDED.city,
  zip_code=EXCLUDED.zip_code,longitude=EXCLUDED.longitude,latitude=EXCLUDED.latitude,
  property_type=EXCLUDED.property_type,land_use_code=EXCLUDED.land_use_code,
  year_built=EXCLUDED.year_built,living_area=EXCLUDED.living_area,land_area=EXCLUDED.land_area,
  land_area_unit=EXCLUDED.land_area_unit,land_value=EXCLUDED.land_value,
  improvement_value=EXCLUDED.improvement_value,total_assessed_value=EXCLUDED.total_assessed_value,
  source_updated_at=EXCLUDED.source_updated_at,
  house_number_unavailable=EXCLUDED.house_number_unavailable,
  source_hash=EXCLUDED.source_hash,imported_at=NOW()
WHERE public_property_snapshots.source_hash <> EXCLUDED.source_hash
""")
SALE_UPSERT = text("""
INSERT INTO public_property_sales
  (source_id,state,county,source_parcel_id,transaction_id,sale_date,recording_date,
   sale_price,conveyance_code,arms_length,source_hash)
VALUES
  (:source_id,:state,:county,:source_parcel_id,:transaction_id,:sale_date,:recording_date,
   :sale_price,:conveyance_code,:arms_length,:source_hash)
ON CONFLICT (source_id,source_parcel_id,transaction_id) DO UPDATE SET
  sale_date=EXCLUDED.sale_date,sale_price=EXCLUDED.sale_price,
  conveyance_code=EXCLUDED.conveyance_code,source_hash=EXCLUDED.source_hash,imported_at=NOW()
WHERE public_property_sales.source_hash <> EXCLUDED.source_hash
""")


async def run(county: str | None, limit: int | None, dry_run: bool,
              start_offset: int = 0, page_size: int = PAGE_SIZE) -> None:
    seen = snapshots = sales_count = 0
    async with httpx.AsyncClient(timeout=90, headers={"User-Agent": "nj-sheriff-sale-platform/1.0"}) as client:
        async for batch in pages(client, county, limit, start_offset, page_size):
            parsed = [parse_row(row) for row in batch]
            snapshot_rows = [snapshot.params() for snapshot, _ in parsed if snapshot]
            sale_rows = [sale.params() for _, sales in parsed for sale in sales]
            if not dry_run and snapshot_rows:
                with warehouse_engine.begin() as connection:
                    connection.execute(text("""INSERT INTO public_data_sources
                      (source_id,state,source_name,source_url,access_method,coverage_notes,last_checked_at)
                      VALUES(:id,'MD','Maryland SDAT/MDP statewide real property assessments',
                      :url,'socrata_api','Statewide current assessment plus three transfer segments',NOW())
                      ON CONFLICT(source_id) DO UPDATE SET last_checked_at=NOW(),updated_at=NOW()"""),
                      {"id": SOURCE_ID, "url": SOURCE_PAGE})
                    connection.execute(SNAPSHOT_UPSERT, snapshot_rows)
                    if sale_rows:
                        connection.execute(SALE_UPSERT, sale_rows)
            seen += len(batch); snapshots += len(snapshot_rows); sales_count += len(sale_rows)
            print(f"records={seen:,} snapshots={snapshots:,} sales={sales_count:,}")
    print(f"complete dry_run={dry_run} records={seen:,} snapshots={snapshots:,} sales={sales_count:,}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--county", help="Exact Maryland county name")
    parser.add_argument("--limit", type=int, help="Maximum source records")
    parser.add_argument("--start-offset", type=int, default=0,
                        help="Source offset used to resume a committed import")
    parser.add_argument("--page-size", type=int, default=PAGE_SIZE,
                        help="Socrata records per request (maximum 50000)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply-migration", action="store_true")
    args = parser.parse_args()
    if args.apply_migration:
        with warehouse_engine.begin() as connection:
            connection.connection.cursor().execute(MIGRATION.read_text())
    if not 1 <= args.page_size <= 50_000:
        parser.error("--page-size must be between 1 and 50000")
    asyncio.run(run(args.county, args.limit, args.dry_run,
                    args.start_offset, args.page_size))


if __name__ == "__main__":
    main()
