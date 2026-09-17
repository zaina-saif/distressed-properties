"""Import VGIN's public statewide parcel Local Schema Tables into the warehouse.

Locality schemas differ, so mappings deliberately use a conservative set of
known field aliases. Owner, mailing, grantor and grantee fields are never read.
"""
from __future__ import annotations

import argparse
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator

import pyogrio
from psycopg2.extras import execute_values
from pyogrio.raw import read
from sqlalchemy import text

from app.database.session import warehouse_engine
from pipeline.public_property_records import decimal_value, integer_value, stable_hash, text_value

SOURCE_ID = "va_vgin_local_schemas_2026q2"
SOURCE_PAGE = "https://vgin.vdem.virginia.gov/datasets/virginia-parcels-local-schema-tables/about"
DOWNLOAD_URL = "https://www.arcgis.com/sharing/rest/content/items/523d89ebf23d4d84957f9fe5b9158bd9/data"
SNAPSHOT_YEAR = 2026

ALIASES = {
    "address": ("PROPADDR", "PROPERTYADDRESS", "PROPERTYLOCATION", "SITUS", "SITUSADDR",
                "SITUSADDRESS", "SITUSFULLADDRESS", "F911ADDRESS", "FULLADDRESS", "LOCATION",
                "LOCATIONADDRESS", "STREETADDRESS", "PADDRESS"),
    "city": ("PROPCITY", "SITUSCITY", "LOCATIONCITY"),
    "zip": ("PROPZIP", "SITUSZIP", "LOCATIONZIP"),
    "property_type": ("PROPERTYCLASS", "PROPCLASS", "STATECLASS", "CLASS", "CLASSTYPE",
                      "PARCELTYPE", "PROPTYPE", "TYPEPROP", "CLASSDESC"),
    "land_use": ("LANDUSE", "LANDUSECODE", "LANDUSEVA", "CRTLANDUSE", "CURRENTLANDUSE"),
    "year_built": ("YEARBUILT", "YEARBLT", "YRBLT", "YEARBILT", "MYRBLT", "RESYRBLT",
                   "MAINSTRUCTURE1YEARBUILT", "NDYEARBUI"),
    "living_area": ("LIVINGAREA", "LIVINGARE", "RESAREA", "RESFLRAREA", "PRCLIVING",
                    "TOTSQFT", "TOTALSQFT", "GROSSBUILDINGAREA", "MAINSTRUCTURE1HEATEDSQFT"),
    "land_area": ("ACRES", "ACREAGE", "PARCELSIZE", "LANDSQFT", "LANDSQFT", "PRCTTLLNDAREAACRES"),
    "bedrooms": ("BEDROOMS", "BEDS", "BEDROOMCN", "NUMBBEDR", "TOTALBEDRO",
                 "MAINSTRUCTURE1BEDROOMS", "VNSNUMBEDRM"),
    "full_baths": ("FULLBATH", "FULLBATHS", "BATHS", "BATHROOMC", "NUMBBATH",
                   "MAINSTRUCTURE1BATHROOMS", "VNSNUMBATHS"),
    "half_baths": ("HALFBATH", "HALFBATHS", "HALFBATHCO", "VNSNUMHBATHS"),
    "land_value": ("LANDVALUE", "LANDVAL", "LANDVALUE1", "TOTALLANDVALUE", "CURRENTLANDVALUE",
                   "ASSESSLAND", "ASLANDVAL1"),
    "improvement_value": ("BLDGVALUE", "BLDGVAL", "IMPVALUE", "IMPROVVALUE", "HOMEVALUE",
                          "DWELLINGVA", "TOTALBUILDINGVALUE", "TOTALIMPROVEMENTSVALUE",
                          "ASSESSBUILDING", "ASBLDGVAL1"),
    "total_value": ("TOTALVALUE", "TOTALVAL", "TOTALVALU", "TOTALASSESSED", "TOTALASSESSEDVALUE",
                    "ASSESSMENT", "TOTASSESS", "ASSESSTOTAL", "CURRENTTOTALVALUE",
                    "TOTALASSESSED", "ASTOTALASSESSVAL1"),
}
SNAPSHOT_COLUMNS = (
    "source_id", "state", "county", "source_parcel_id", "snapshot_year", "street_address",
    "city", "zip_code", "property_type", "land_use_code", "year_built", "living_area",
    "land_area", "land_area_unit", "bedrooms", "bathrooms", "land_value",
    "improvement_value", "total_assessed_value", "source_updated_at", "source_hash",
)
SNAPSHOT_SQL = f"""
INSERT INTO public_property_snapshots ({','.join(SNAPSHOT_COLUMNS)}) VALUES %s
ON CONFLICT (source_id,source_parcel_id,snapshot_year) DO UPDATE SET
 county=EXCLUDED.county,street_address=EXCLUDED.street_address,city=EXCLUDED.city,
 zip_code=EXCLUDED.zip_code,property_type=EXCLUDED.property_type,
 land_use_code=EXCLUDED.land_use_code,year_built=EXCLUDED.year_built,
 living_area=EXCLUDED.living_area,land_area=EXCLUDED.land_area,
 land_area_unit=EXCLUDED.land_area_unit,bedrooms=EXCLUDED.bedrooms,
 bathrooms=EXCLUDED.bathrooms,land_value=EXCLUDED.land_value,
 improvement_value=EXCLUDED.improvement_value,total_assessed_value=EXCLUDED.total_assessed_value,
 source_updated_at=EXCLUDED.source_updated_at,source_hash=EXCLUDED.source_hash,imported_at=NOW()
WHERE public_property_snapshots.source_hash <> EXCLUDED.source_hash
"""
SALE_COLUMNS = ("source_id", "state", "county", "source_parcel_id", "transaction_id",
                "sale_date", "sale_price", "arms_length", "source_hash")
SALE_SQL = f"""
INSERT INTO public_property_sales ({','.join(SALE_COLUMNS)}) VALUES %s
ON CONFLICT (source_id,source_parcel_id,transaction_id) DO UPDATE SET
 sale_date=EXCLUDED.sale_date,sale_price=EXCLUDED.sale_price,
 arms_length=EXCLUDED.arms_length,source_hash=EXCLUDED.source_hash,imported_at=NOW()
WHERE public_property_sales.source_hash <> EXCLUDED.source_hash
"""


def normalized(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def field_map(fields: list[str]) -> dict[str, str]:
    return {normalized(field): field for field in fields}


def first(row: dict[str, Any], fields: dict[str, str], key: str) -> Any:
    for alias in ALIASES[key]:
        field = fields.get(alias)
        if field is not None:
            value = row.get(field)
            if text_value(value) is not None:
                return value
    return None


def parcel_identity(value: Any) -> str | None:
    if value is None:
        return None
    try:
        number = Decimal(str(value))
        return f"51-{int(number)}" if number == number.to_integral_value() else f"51-{number}"
    except Exception:
        value = text_value(value)
        return f"51-{value}" if value else None


def parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value.date()
    elif isinstance(value, date):
        parsed = value
    else:
        raw = text_value(value)
        if not raw or re.fullmatch(r"\d{4}", raw):
            return None
        parsed = None
        for form in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%d-%b-%Y", "%Y%m%d"):
            try:
                parsed = datetime.strptime(raw, form).date()
                break
            except ValueError:
                pass
        if parsed is None:
            return None
    # Several locality exports use Excel's 1900-01-01 sentinel for an unknown
    # date. It must not become a synthetic sale in AVM training history.
    return parsed if date(1800, 1, 1) <= parsed <= date.today() and parsed != date(1900, 1, 1) else None


def source_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=value.tzinfo or timezone.utc)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)
    return None


def parse_snapshot(row: dict[str, Any], fields: dict[str, str], locality: str) -> tuple[Any, ...] | None:
    qpid_field = fields.get("VGINQPID")
    identity = parcel_identity(row.get(qpid_field)) if qpid_field else None
    if not identity:
        return None
    land_area = decimal_value(first(row, fields, "land_area"))
    land_unit = None
    if land_area is not None and land_area > 0:
        selected = next((alias for alias in ALIASES["land_area"] if fields.get(alias)
                         and text_value(row.get(fields[alias])) is not None), "")
        land_unit = "square feet" if "SQFT" in selected else "acres" if "ACRE" in selected or selected == "PARCELSIZE" else "source units"
    else:
        land_area = None
    full = decimal_value(first(row, fields, "full_baths"))
    half = decimal_value(first(row, fields, "half_baths"))
    bathrooms = (full or 0) + (half or 0) / Decimal(2) if full is not None or half is not None else None
    year_built = integer_value(first(row, fields, "year_built"))
    if year_built is not None and not 1600 <= year_built <= date.today().year + 1:
        year_built = None
    updated_field = fields.get("LASTUPDATE")
    core = {
        "source_id": SOURCE_ID, "state": "VA", "county": locality,
        "source_parcel_id": identity, "snapshot_year": SNAPSHOT_YEAR,
        "street_address": text_value(first(row, fields, "address")),
        "city": text_value(first(row, fields, "city")), "zip_code": text_value(first(row, fields, "zip")),
        "property_type": text_value(first(row, fields, "property_type")),
        "land_use_code": text_value(first(row, fields, "land_use")),
        "year_built": year_built,
        "living_area": integer_value(first(row, fields, "living_area")),
        "land_area": land_area, "land_area_unit": land_unit,
        "bedrooms": decimal_value(first(row, fields, "bedrooms")), "bathrooms": bathrooms,
        "land_value": decimal_value(first(row, fields, "land_value")),
        "improvement_value": decimal_value(first(row, fields, "improvement_value")),
        "total_assessed_value": decimal_value(first(row, fields, "total_value")),
        "source_updated_at": source_timestamp(row.get(updated_field)) if updated_field else None,
    }
    return tuple(core[name] for name in SNAPSHOT_COLUMNS[:-1]) + (stable_hash(core),)


def sale_pairs(row: dict[str, Any], fields: dict[str, str]) -> Iterator[tuple[date, Decimal, int]]:
    date_aliases = (("SALEDATE", "SALEPRICE"), ("LASTSALEDA", "LASTSALEPR"),
                    ("MOSTRECENTSALEDATE", "MOSTRECENTSALEPRICE"), ("SALEDATE1", "SALEPRICE1"))
    for index in range(1, 7):
        date_aliases += ((f"SALE{index}D", f"SALE{index}AMT"),
                         (f"SALEDATE{index}", f"SALEPRICE{index}"))
    seen: set[tuple[date, Decimal]] = set()
    for position, (date_alias, price_alias) in enumerate(date_aliases, 1):
        date_field, price_field = fields.get(date_alias), fields.get(price_alias)
        if not date_field or not price_field:
            continue
        parsed_date = parse_date(row.get(date_field))
        price = decimal_value(row.get(price_field))
        if parsed_date and price is not None and price > 0 and (parsed_date, price) not in seen:
            seen.add((parsed_date, price))
            yield parsed_date, price, position


def parse_sales(row: dict[str, Any], fields: dict[str, str], locality: str) -> Iterator[tuple[Any, ...]]:
    qpid_field = fields.get("VGINQPID")
    identity = parcel_identity(row.get(qpid_field)) if qpid_field else None
    if not identity:
        return
    for sale_date, sale_price, position in sale_pairs(row, fields):
        transaction = stable_hash({"parcel": identity, "date": sale_date, "price": sale_price,
                                   "position": position})[:32]
        core = {"source_id": SOURCE_ID, "state": "VA", "county": locality,
                "source_parcel_id": identity, "transaction_id": transaction,
                "sale_date": sale_date, "sale_price": sale_price, "arms_length": None}
        yield tuple(core[name] for name in SALE_COLUMNS[:-1]) + (stable_hash(core),)


def table_rows(gdb: Path, layer: str, columns: list[str], chunk_size: int) -> Iterator[dict[str, Any]]:
    count = pyogrio.read_info(gdb, layer=layer)["features"]
    for offset in range(0, count, chunk_size):
        meta, _, _, arrays = read(gdb, layer=layer, columns=columns, read_geometry=False,
                                  skip_features=offset, max_features=chunk_size,
                                  datetime_as_string=False)
        names = list(meta["fields"])
        for values in zip(*arrays):
            yield dict(zip(names, values))


def import_layer(gdb: Path, layer: str, batch_size: int, dry_run: bool) -> tuple[int, int]:
    info = pyogrio.read_info(gdb, layer=layer)
    fields_list = list(info["fields"])
    fields = field_map(fields_list)
    locality = layer.removeprefix("TBL_").replace("_", " ")
    safe_columns = [field for field in fields_list if not re.search(r"OWNER|MAIL|GRANTOR|GRANTEE", field, re.I)]
    connection = warehouse_engine.raw_connection() if not dry_run else None
    snapshots = sales = 0
    try:
        cursor = connection.cursor() if connection else None
        snapshot_batch: list[tuple[Any, ...]] = []
        sale_batch: list[tuple[Any, ...]] = []
        for row in table_rows(gdb, layer, safe_columns, batch_size):
            snapshot = parse_snapshot(row, fields, locality)
            if snapshot:
                snapshot_batch.append(snapshot)
            sale_batch.extend(parse_sales(row, fields, locality))
            if len(snapshot_batch) >= batch_size:
                if cursor: execute_values(cursor, SNAPSHOT_SQL, snapshot_batch, page_size=batch_size); connection.commit()
                snapshots += len(snapshot_batch); snapshot_batch.clear()
            if len(sale_batch) >= batch_size:
                if cursor: execute_values(cursor, SALE_SQL, sale_batch, page_size=batch_size); connection.commit()
                sales += len(sale_batch); sale_batch.clear()
        if cursor:
            if snapshot_batch: execute_values(cursor, SNAPSHOT_SQL, snapshot_batch, page_size=batch_size)
            if sale_batch: execute_values(cursor, SALE_SQL, sale_batch, page_size=batch_size)
            connection.commit()
        snapshots += len(snapshot_batch); sales += len(sale_batch)
        if connection:
            with connection.cursor() as manifest:
                manifest.execute("""
                    INSERT INTO public_import_files(source_id,file_name,file_url,row_count,status,completed_at)
                    VALUES(%s,%s,%s,%s,'completed',NOW())
                    ON CONFLICT(source_id,file_name) DO UPDATE SET row_count=EXCLUDED.row_count,
                      status='completed',completed_at=NOW()
                """, (SOURCE_ID, layer, DOWNLOAD_URL, snapshots + sales))
            connection.commit()
    finally:
        if connection: connection.close()
    print(f"complete Virginia {locality}: snapshots={snapshots:,} sales={sales:,}", flush=True)
    return snapshots, sales


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gdb", required=True, type=Path)
    parser.add_argument("--locality")
    parser.add_argument("--batch-size", type=int, default=5_000)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    layers = [name for name, _ in pyogrio.list_layers(args.gdb) if name.startswith("TBL_")]
    if args.locality:
        wanted = normalized(args.locality)
        layers = [name for name in layers if normalized(name.removeprefix("TBL_")) == wanted]
        if not layers: raise SystemExit(f"Unknown Virginia locality: {args.locality}")
    if not args.dry_run:
        with warehouse_engine.begin() as connection:
            connection.execute(text("""
                INSERT INTO public_data_sources(source_id,state,source_name,source_url,access_method,coverage_notes,last_checked_at)
                VALUES(:id,'VA','VGIN Virginia Parcels Local Schema Tables 2026 Q2',:url,'file_geodatabase',
                  'Locality-submitted parcel attributes; conservative cross-schema mapping; owner, mailing and party names excluded',NOW())
                ON CONFLICT(source_id) DO UPDATE SET last_checked_at=NOW(),updated_at=NOW()
            """), {"id": SOURCE_ID, "url": SOURCE_PAGE})
    completed = set()
    if not args.dry_run:
        with warehouse_engine.connect() as connection:
            completed = set(connection.execute(text("SELECT file_name FROM public_import_files WHERE source_id=:id AND status='completed'"), {"id": SOURCE_ID}).scalars())
    for layer in layers:
        if layer in completed:
            print(f"skip completed {layer}", flush=True)
        else:
            import_layer(args.gdb, layer, args.batch_size, args.dry_run)


if __name__ == "__main__":
    main()
