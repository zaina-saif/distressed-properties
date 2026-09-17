"""Load Cook County Assessor history into canonical public AVM tables.

All queries explicitly select non-personal fields. Owner, mailing, buyer, and
seller fields published alongside some feeds are never requested.
"""
from __future__ import annotations

import argparse
import csv
import time
from datetime import date
from decimal import Decimal
from typing import Any, Callable, Iterator

import httpx
from psycopg2.extras import execute_values
from sqlalchemy import text

from app.database.session import warehouse_engine
from pipeline.public_property_records import date_value, decimal_value, integer_value, stable_hash, text_value

SOURCE_ID = "il_cook_assessor_1999_present"
SOURCE_PAGE = "https://datacatalog.cookcountyil.gov/browse?tags=assessor"
HOST = "https://datacatalog.cookcountyil.gov/resource"
TODAY = date.today()

SNAPSHOT_COLUMNS = (
    "source_id", "state", "county", "source_parcel_id", "snapshot_year", "street_address",
    "city", "zip_code", "longitude", "latitude", "property_type", "land_use_code",
    "year_built", "living_area", "land_area", "land_area_unit", "bedrooms", "bathrooms",
    "land_value", "improvement_value", "total_assessed_value", "source_hash",
)
INSERT_SNAPSHOT = f"INSERT INTO public_property_snapshots ({','.join(SNAPSHOT_COLUMNS)}) VALUES %s"
BASE_CONFLICT = " ON CONFLICT (source_id,source_parcel_id,snapshot_year) DO UPDATE SET "

ASSESSMENT_SQL = INSERT_SNAPSHOT + BASE_CONFLICT + """
 property_type=COALESCE(EXCLUDED.property_type,public_property_snapshots.property_type),
 land_use_code=COALESCE(EXCLUDED.land_use_code,public_property_snapshots.land_use_code),
 land_value=EXCLUDED.land_value,improvement_value=EXCLUDED.improvement_value,
 total_assessed_value=EXCLUDED.total_assessed_value,source_hash=EXCLUDED.source_hash,imported_at=NOW()
"""
CHAR_SQL = INSERT_SNAPSHOT + BASE_CONFLICT + """
 property_type=COALESCE(EXCLUDED.property_type,public_property_snapshots.property_type),
 land_use_code=COALESCE(EXCLUDED.land_use_code,public_property_snapshots.land_use_code),
 year_built=EXCLUDED.year_built,living_area=EXCLUDED.living_area,land_area=EXCLUDED.land_area,
 land_area_unit=EXCLUDED.land_area_unit,bedrooms=EXCLUDED.bedrooms,bathrooms=EXCLUDED.bathrooms,
 source_hash=EXCLUDED.source_hash,imported_at=NOW()
"""
ADDRESS_SQL = INSERT_SNAPSHOT + BASE_CONFLICT + """
 street_address=EXCLUDED.street_address,city=EXCLUDED.city,zip_code=EXCLUDED.zip_code,
 source_hash=EXCLUDED.source_hash,imported_at=NOW()
"""
UNIVERSE_SQL = INSERT_SNAPSHOT + BASE_CONFLICT + """
 zip_code=COALESCE(EXCLUDED.zip_code,public_property_snapshots.zip_code),longitude=EXCLUDED.longitude,
 latitude=EXCLUDED.latitude,property_type=COALESCE(EXCLUDED.property_type,public_property_snapshots.property_type),
 land_use_code=COALESCE(EXCLUDED.land_use_code,public_property_snapshots.land_use_code),
 source_hash=EXCLUDED.source_hash,imported_at=NOW()
"""
SALE_COLUMNS = ("source_id", "state", "county", "source_parcel_id", "transaction_id",
                "sale_date", "recording_date", "sale_price", "conveyance_code", "arms_length", "source_hash")
SALE_SQL = f"""INSERT INTO public_property_sales ({','.join(SALE_COLUMNS)}) VALUES %s
ON CONFLICT(source_id,source_parcel_id,transaction_id) DO UPDATE SET sale_date=EXCLUDED.sale_date,
 sale_price=EXCLUDED.sale_price,conveyance_code=EXCLUDED.conveyance_code,
 arms_length=EXCLUDED.arms_length,source_hash=EXCLUDED.source_hash,imported_at=NOW()
WHERE public_property_sales.source_hash<>EXCLUDED.source_hash"""


def flag(value: Any) -> bool:
    return (text_value(value) or "").lower() in {"true", "t", "yes", "1"}


def parcel(value: Any) -> str | None:
    pin = text_value(value)
    return f"IL:COOK:{''.join(pin.upper().split())}" if pin else None


def year_value(value: Any) -> int | None:
    year = integer_value(value)
    return year if year and 1999 <= year <= TODAY.year else None


def blank_snapshot(row: dict[str, Any]) -> dict[str, Any] | None:
    identity, year = parcel(row.get("pin")), year_value(row.get("year"))
    if not identity or not year:
        return None
    return {name: None for name in SNAPSHOT_COLUMNS} | {
        "source_id": SOURCE_ID, "state": "IL", "county": "Cook",
        "source_parcel_id": identity, "snapshot_year": year,
    }


def finish_snapshot(core: dict[str, Any]) -> tuple[Any, ...]:
    hashed = {name: core[name] for name in SNAPSHOT_COLUMNS[:-1]}
    core["source_hash"] = stable_hash(hashed)
    return tuple(core[name] for name in SNAPSHOT_COLUMNS)


def parse_assessment(row: dict[str, Any]) -> tuple[Any, ...] | None:
    core = blank_snapshot(row)
    if not core: return None
    def final(prefix: str) -> Decimal | None:
        for stage in ("board", "certified", "mailed"):
            value = decimal_value(row.get(f"{stage}_{prefix}"))
            if value is not None: return value
        return None
    core.update(property_type=text_value(row.get("class")), land_use_code=text_value(row.get("class")),
                land_value=final("land"), improvement_value=final("bldg"), total_assessed_value=final("tot"))
    return finish_snapshot(core)


def parse_characteristic(row: dict[str, Any], condo: bool = False) -> tuple[Any, ...] | None:
    core = blank_snapshot(row)
    if not core: return None
    year = core["snapshot_year"]
    built = integer_value(row.get("char_yrblt"))
    full = decimal_value(row.get("char_full_baths" if condo else "char_fbath"))
    half = decimal_value(row.get("char_half_baths" if condo else "char_hbath"))
    baths = (full or Decimal(0)) + (half or Decimal(0)) / 2 if full is not None or half is not None else None
    core.update(property_type="Condominium" if condo else text_value(row.get("char_type_resd")),
                land_use_code=text_value(row.get("class")) or text_value(row.get("char_use")),
                year_built=built if built and 1600 <= built <= year else None,
                living_area=integer_value(row.get("char_unit_sf" if condo else "char_bldg_sf")),
                land_area=decimal_value(row.get("char_land_sf")), land_area_unit="square feet",
                bedrooms=decimal_value(row.get("char_bedrooms" if condo else "char_beds")), bathrooms=baths)
    return finish_snapshot(core)


def parse_address(row: dict[str, Any]) -> tuple[Any, ...] | None:
    core = blank_snapshot(row)
    if not core: return None
    core.update(street_address=text_value(row.get("prop_address_full")),
                city=text_value(row.get("prop_address_city_name")), zip_code=text_value(row.get("prop_address_zipcode_1")))
    return finish_snapshot(core)


def parse_universe(row: dict[str, Any]) -> tuple[Any, ...] | None:
    core = blank_snapshot(row)
    if not core: return None
    core.update(zip_code=text_value(row.get("zip_code")), longitude=decimal_value(row.get("lon")),
                latitude=decimal_value(row.get("lat")), property_type=text_value(row.get("class")),
                land_use_code=text_value(row.get("class")))
    return finish_snapshot(core)


def parse_sale(row: dict[str, Any]) -> tuple[Any, ...] | None:
    identity, occurred, price = parcel(row.get("pin")), date_value(row.get("sale_date")), decimal_value(row.get("sale_price"))
    if not identity or not occurred or not date(1970, 1, 1) <= occurred <= TODAY or price is None or price <= 0: return None
    rejected = any(flag(row.get(name)) for name in ("sale_filter_same_sale_within_365", "sale_filter_less_than_10k", "sale_filter_deed_type"))
    transaction = text_value(row.get("row_id")) or text_value(row.get("doc_no")) or stable_hash({"pin": identity, "date": occurred, "price": price})[:32]
    conveyance = ";".join(filter(None, (text_value(row.get("deed_type")), text_value(row.get("mydec_deed_type")), text_value(row.get("sale_type"))))) or None
    core = {"source_id": SOURCE_ID, "state": "IL", "county": "Cook", "source_parcel_id": identity,
            "transaction_id": transaction, "sale_date": occurred, "recording_date": None,
            "sale_price": price, "conveyance_code": conveyance, "arms_length": not rejected}
    return tuple(core[name] for name in SALE_COLUMNS[:-1]) + (stable_hash(core),)


FEEDS: dict[str, tuple[str, tuple[str, ...], Callable, str, str | None]] = {
    "assessments_current": ("uzyt-m557", ("pin","year","class","mailed_bldg","mailed_land","mailed_tot","certified_bldg","certified_land","certified_tot","board_bldg","board_land","board_tot","row_id"), parse_assessment, ASSESSMENT_SQL, f"year={TODAY.year}"),
    "houses_current": ("x54s-btds", ("pin","year","class","card","char_yrblt","char_bldg_sf","char_land_sf","char_beds","char_fbath","char_hbath","char_type_resd","char_use","row_id"), parse_characteristic, CHAR_SQL, f"card=1 AND year={TODAY.year}"),
    "condos_current": ("3r7i-mrz4", ("pin","year","class","card","char_yrblt","char_unit_sf","char_land_sf","char_bedrooms","char_full_baths","char_half_baths","row_id"), lambda row: parse_characteristic(row, True), CHAR_SQL, f"card=1 AND year={TODAY.year}"),
    "assessments": ("uzyt-m557", ("pin","year","class","mailed_bldg","mailed_land","mailed_tot","certified_bldg","certified_land","certified_tot","board_bldg","board_land","board_tot","row_id"), parse_assessment, ASSESSMENT_SQL, None),
    "houses": ("x54s-btds", ("pin","year","class","card","char_yrblt","char_bldg_sf","char_land_sf","char_beds","char_fbath","char_hbath","char_type_resd","char_use","row_id"), parse_characteristic, CHAR_SQL, "card=1"),
    "condos": ("3r7i-mrz4", ("pin","year","class","card","char_yrblt","char_unit_sf","char_land_sf","char_bedrooms","char_full_baths","char_half_baths","row_id"), lambda row: parse_characteristic(row, True), CHAR_SQL, "card=1"),
    "addresses": ("3723-97qp", ("pin","year","prop_address_full","prop_address_city_name","prop_address_zipcode_1","row_id"), parse_address, ADDRESS_SQL, f"year={TODAY.year}"),
    "universe": ("pabr-t5kh", ("pin","year","class","zip_code","lon","lat","row_id"), parse_universe, UNIVERSE_SQL, None),
    "sales": ("wvhk-k5uv", ("pin","year","class","sale_date","sale_price","doc_no","deed_type","mydec_deed_type","is_multisale","num_parcels_sale","sale_type","sale_filter_same_sale_within_365","sale_filter_less_than_10k","sale_filter_deed_type","row_id"), parse_sale, SALE_SQL, None),
}


def ensure_metadata() -> None:
    with warehouse_engine.begin() as connection:
        connection.execute(text("""CREATE TABLE IF NOT EXISTS public_import_checkpoints(
          source_id TEXT NOT NULL,feed_id TEXT NOT NULL,last_key TEXT,rows_processed BIGINT NOT NULL DEFAULT 0,
          completed BOOLEAN NOT NULL DEFAULT FALSE,updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),PRIMARY KEY(source_id,feed_id))"""))
        connection.execute(text("""INSERT INTO public_data_sources(source_id,state,county,source_name,source_url,access_method,coverage_notes,last_checked_at)
          VALUES(:id,'IL','Cook','Cook County Assessor Open Data',:url,'Socrata API',
          '1999-current assessments, characteristics and sales plus current addresses/geography; identity fields excluded',NOW())
          ON CONFLICT(source_id) DO UPDATE SET last_checked_at=NOW(),updated_at=NOW()"""), {"id": SOURCE_ID, "url": SOURCE_PAGE})


def get_checkpoint(feed: str) -> tuple[str | None, int, bool]:
    with warehouse_engine.begin() as connection:
        row = connection.execute(text("SELECT last_key,rows_processed,completed FROM public_import_checkpoints WHERE source_id=:s AND feed_id=:f"), {"s": SOURCE_ID, "f": feed}).first()
    return (row[0], row[1], row[2]) if row else (None, 0, False)


def rows(client: httpx.Client, dataset: str, fields: tuple[str, ...], page_size: int, after: str | None, where: str | None) -> Iterator[tuple[dict[str, str], bool]]:
    while True:
        base_where = f"row_id > '{after.replace("'", "''")}'" if after else None
        condition = f"({where}) AND ({base_where})" if where and base_where else where or base_where
        params = {"$select": ",".join(fields), "$order": "row_id", "$limit": page_size}
        if condition: params["$where"] = condition
        for attempt in range(10):
            try:
                with client.stream("GET", f"{HOST}/{dataset}.csv", params=params) as response:
                    response.raise_for_status(); reader = csv.DictReader(response.iter_lines()); page = list(reader)
                break
            except httpx.HTTPError:
                if attempt == 9: raise
                time.sleep(min(2 ** attempt, 30))
        if not page: break
        for index, row in enumerate(page): yield row, index == len(page) - 1
        after = page[-1]["row_id"]
        if len(page) < page_size: break


def load_feed(name: str, page_size: int, batch_size: int) -> int:
    dataset, fields, parser, sql, where = FEEDS[name]
    after, processed, complete = get_checkpoint(name)
    if complete: print(f"{name}: already complete ({processed:,})", flush=True); return processed
    raw = warehouse_engine.raw_connection(); batch = []; page_last = after
    try:
        cursor = raw.cursor()
        with httpx.Client(follow_redirects=True, timeout=300) as client:
            for row, end_page in rows(client, dataset, fields, page_size, after, where):
                parsed = parser(row); processed += 1
                if parsed: batch.append(parsed)
                if len(batch) >= batch_size:
                    execute_values(cursor, sql, batch, page_size=batch_size); batch.clear()
                if end_page:
                    if batch: execute_values(cursor, sql, batch, page_size=batch_size); batch.clear()
                    page_last = row["row_id"]
                    cursor.execute("""INSERT INTO public_import_checkpoints(source_id,feed_id,last_key,rows_processed,completed,updated_at)
                      VALUES(%s,%s,%s,%s,FALSE,NOW()) ON CONFLICT(source_id,feed_id) DO UPDATE SET
                      last_key=EXCLUDED.last_key,rows_processed=EXCLUDED.rows_processed,updated_at=NOW()""", (SOURCE_ID,name,page_last,processed))
                    raw.commit(); print(f"{name}: {processed:,}", flush=True)
        cursor.execute("""INSERT INTO public_import_checkpoints(source_id,feed_id,last_key,rows_processed,completed,updated_at)
          VALUES(%s,%s,%s,%s,TRUE,NOW()) ON CONFLICT(source_id,feed_id) DO UPDATE SET completed=TRUE,updated_at=NOW()""", (SOURCE_ID,name,page_last,processed)); raw.commit()
    finally: raw.close()
    print(f"{name}: complete {processed:,}", flush=True); return processed


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--feed", choices=(*FEEDS, "all"), default="all")
    parser.add_argument("--page-size", type=int, default=100_000); parser.add_argument("--batch-size", type=int, default=10_000)
    args = parser.parse_args(); ensure_metadata()
    names = FEEDS if args.feed == "all" else (args.feed,)
    for name in names: load_feed(name, args.page_size, args.batch_size)


if __name__ == "__main__": main()
