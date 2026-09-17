"""Import Illinois IDOR MyDec real-estate transfer declarations.

Only parcel, property, and transaction fields are requested. Buyer, seller,
agent, preparer, organization, and mailing fields are deliberately excluded.
"""
from __future__ import annotations

import argparse
import csv
import time
from datetime import date
from decimal import Decimal
from typing import Any, Iterator

import httpx
from psycopg2.extras import execute_values
from sqlalchemy import text

from app.database.session import warehouse_engine
from pipeline.public_property_records import date_value, decimal_value, stable_hash, text_value

SOURCE_ID = "il_idor_mydec_2014_present"
SOURCE_PAGE = "https://tax.illinois.gov/localgovernments/property/mydecdatafiles.html"
API_URL = "https://data.illinois.gov/resource/it54-y4c6.csv"

DISTRESS_FLAGS = {
    "line_10b_sale_between_related": "related",
    "line_10c_transfer_of_100": "partial-interest",
    "line_10d_court_ordered_sale": "court-ordered",
    "line_10e_sale_in_lieu_of": "deed-in-lieu",
    "line_10f_condemnation": "condemnation",
    "line_10g_short_sale": "short-sale",
    "line_10h_bank_reo": "bank-reo",
    "line_10i_auction_sale": "auction",
    "line_10j_seller_buyer_is": "relocation-company",
    "line_10k_seller_buyer_is": "financial-institution-or-government",
    "line_10l_buyer_is_a_real": "reit",
    "line_10m_buyer_is_a_pension": "pension-fund",
    "line_10n_buyer_is_an_adjacent": "adjacent-owner",
    "line_10o_buyer_is_exercising": "purchase-option",
    "line_10p_trade_of_property": "property-trade",
    "line_10q_sale_leaseback": "sale-leaseback",
    "line_10r_other": "other-condition",
}
FIELDS = (
    "declaration_id", "status", "document_number", "date_recorded", "full_address",
    "line_1_street", "line_1_city", "line_1_zip_code", "line_1_township",
    "line_1_county", "line_1_primary_pin", "line_1_lot_size_or_acreage", "line_1_unit",
    "line_1_split_parcel", "line_2_total_parcels", "line_3_additional_pins",
    "line_4_instrument_date", "line_5_instrument_type", "line_6_principal_residence",
    "line_7_property_advertised", "line_8_current_use", "line_8_current_number_of",
    "line_8_current_commercial", "line_8_current_other_use", "line_8_intended_use",
    "line_9_no_changes", "line_9_demolition_damage", "line_9_additions",
    "line_9_major_remodeling", "line_9_new_construction", "line_9_other_change",
    *DISTRESS_FLAGS.keys(), "line_11_full_consideration", "line_12a_total_personal",
    "line_13_net_consideration", "line_17_net_consideration",
)
SALE_COLUMNS = ("source_id", "state", "county", "source_parcel_id", "transaction_id",
                "sale_date", "recording_date", "sale_price", "conveyance_code",
                "arms_length", "source_hash")
SNAPSHOT_COLUMNS = (
    "source_id", "state", "county", "source_parcel_id", "snapshot_year", "street_address",
    "city", "zip_code", "property_type", "land_use_code", "land_area", "land_area_unit",
    "source_hash",
)
SALE_SQL = f"""
INSERT INTO public_property_sales ({','.join(SALE_COLUMNS)}) VALUES %s
ON CONFLICT (source_id,source_parcel_id,transaction_id) DO UPDATE SET
 county=EXCLUDED.county,sale_date=EXCLUDED.sale_date,recording_date=EXCLUDED.recording_date,
 sale_price=EXCLUDED.sale_price,conveyance_code=EXCLUDED.conveyance_code,
 arms_length=EXCLUDED.arms_length,source_hash=EXCLUDED.source_hash,imported_at=NOW()
WHERE public_property_sales.source_hash <> EXCLUDED.source_hash
"""
SNAPSHOT_SQL = f"""
INSERT INTO public_property_snapshots ({','.join(SNAPSHOT_COLUMNS)}) VALUES %s
ON CONFLICT (source_id,source_parcel_id,snapshot_year) DO UPDATE SET
 county=EXCLUDED.county,street_address=EXCLUDED.street_address,city=EXCLUDED.city,
 zip_code=EXCLUDED.zip_code,property_type=EXCLUDED.property_type,
 land_use_code=EXCLUDED.land_use_code,land_area=EXCLUDED.land_area,
 land_area_unit=EXCLUDED.land_area_unit,source_hash=EXCLUDED.source_hash,imported_at=NOW()
WHERE public_property_snapshots.source_hash <> EXCLUDED.source_hash
"""


def checked(value: Any) -> bool:
    return (text_value(value) or "").lower() in {"true", "t", "yes", "y", "1"}


def parcel_id(row: dict[str, Any]) -> str | None:
    county, pin = text_value(row.get("line_1_county")), text_value(row.get("line_1_primary_pin"))
    if not county or not pin:
        return None
    return f"IL:{county.upper()}:{''.join(pin.upper().split())}"


def sale_price(row: dict[str, Any]) -> Decimal | None:
    # Line 13 excludes declared personal property and is the best real-property amount.
    for name in ("line_13_net_consideration", "line_17_net_consideration", "line_11_full_consideration"):
        value = decimal_value(row.get(name))
        if value is not None and value > 0:
            return value
    return None


def parse_sale(row: dict[str, Any], today: date | None = None) -> tuple[Any, ...] | None:
    identity = parcel_id(row)
    instrument_date, recording_date = date_value(row.get("line_4_instrument_date")), date_value(row.get("date_recorded"))
    occurred = instrument_date or recording_date
    price = sale_price(row)
    today = today or date.today()
    if not identity or not occurred or not date(2013, 1, 1) <= occurred <= today or price is None:
        return None
    conditions = [label for field, label in DISTRESS_FLAGS.items() if checked(row.get(field))]
    advertised = checked(row.get("line_7_property_advertised"))
    arms_length = False if conditions else True if advertised else None
    instrument = text_value(row.get("line_5_instrument_type"))
    conveyance = ";".join(filter(None, [instrument, *conditions])) or None
    transaction = text_value(row.get("declaration_id")) or text_value(row.get("document_number"))
    if not transaction:
        transaction = stable_hash({"parcel": identity, "date": occurred, "price": price})[:32]
    core = {"source_id": SOURCE_ID, "state": "IL", "county": text_value(row.get("line_1_county")),
            "source_parcel_id": identity, "transaction_id": transaction, "sale_date": occurred,
            "recording_date": recording_date, "sale_price": price,
            "conveyance_code": conveyance, "arms_length": arms_length}
    return tuple(core[name] for name in SALE_COLUMNS[:-1]) + (stable_hash(core),)


def parse_snapshot(row: dict[str, Any], today: date | None = None) -> tuple[Any, ...] | None:
    identity = parcel_id(row)
    observed = date_value(row.get("date_recorded")) or date_value(row.get("line_4_instrument_date"))
    today = today or date.today()
    if not identity or not observed or not date(2013, 1, 1) <= observed <= today:
        return None
    area = decimal_value(row.get("line_1_lot_size_or_acreage"))
    unit = text_value(row.get("line_1_unit"))
    core = {"source_id": SOURCE_ID, "state": "IL", "county": text_value(row.get("line_1_county")),
            "source_parcel_id": identity, "snapshot_year": observed.year,
            "street_address": text_value(row.get("line_1_street")) or text_value(row.get("full_address")),
            "city": text_value(row.get("line_1_city")), "zip_code": text_value(row.get("line_1_zip_code")),
            "property_type": text_value(row.get("line_8_current_use")),
            "land_use_code": text_value(row.get("line_8_current_use")),
            # MyDec is declarant-entered and contains occasional malformed extremes.
            "land_area": area if area is not None and Decimal(0) <= area < Decimal("1000000000000") else None,
            "land_area_unit": unit}
    return tuple(core[name] for name in SNAPSHOT_COLUMNS[:-1]) + (stable_hash(core),)


def api_rows(client: httpx.Client, page_size: int, max_retries: int = 10) -> Iterator[dict[str, str]]:
    last_id: str | None = None
    while True:
        count = 0
        for attempt in range(max_retries):
            params = {"$select": ",".join(FIELDS), "$order": "declaration_id", "$limit": page_size}
            if last_id is not None:
                escaped = last_id.replace("'", "''")
                params["$where"] = f"declaration_id > '{escaped}'"
            try:
                with client.stream("GET", API_URL, params=params) as response:
                    response.raise_for_status()
                    reader = csv.DictReader(response.iter_lines())
                    count = 0
                    for row in reader:
                        count += 1
                        last_id = row["declaration_id"]
                        yield row
                break
            except httpx.HTTPError as error:
                if attempt + 1 == max_retries:
                    raise
                print(f"API page interrupted after {last_id}; retry {attempt + 1}/{max_retries}: {error}", flush=True)
                time.sleep(min(2 ** attempt, 30))
        if count < page_size:
            break


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--page-size", type=int, default=25_000)
    parser.add_argument("--batch-size", type=int, default=10_000)
    parser.add_argument("--max-rows", type=int)
    args = parser.parse_args()
    with warehouse_engine.begin() as connection:
        connection.execute(text("""
          INSERT INTO public_data_sources(source_id,state,source_name,source_url,access_method,coverage_notes,last_checked_at)
          VALUES(:id,'IL','Illinois IDOR MyDec Transfer Declarations',:url,'Socrata API',
          'Recorded PTAX-203/203-A/203-B declarations, 2014-present; names, organizations, agents, preparers, and mailing fields excluded',NOW())
          ON CONFLICT(source_id) DO UPDATE SET last_checked_at=NOW(),updated_at=NOW()
        """), {"id": SOURCE_ID, "url": SOURCE_PAGE})
    raw = warehouse_engine.raw_connection(); processed = sales = snapshots = 0
    try:
        cursor = raw.cursor(); sale_batch: list[tuple[Any, ...]] = []; snapshot_batch: dict[tuple[str, int], tuple[Any, ...]] = {}
        with httpx.Client(follow_redirects=True, timeout=180) as client:
            for row in api_rows(client, args.page_size):
                processed += 1
                sale = parse_sale(row); snapshot = parse_snapshot(row)
                if sale: sale_batch.append(sale)
                if snapshot: snapshot_batch[(snapshot[3], snapshot[4])] = snapshot
                if len(sale_batch) >= args.batch_size:
                    execute_values(cursor, SALE_SQL, sale_batch, page_size=args.batch_size); sales += len(sale_batch); sale_batch.clear()
                if len(snapshot_batch) >= args.batch_size:
                    execute_values(cursor, SNAPSHOT_SQL, list(snapshot_batch.values()), page_size=args.batch_size); snapshots += len(snapshot_batch); snapshot_batch.clear()
                if processed % 100_000 == 0:
                    raw.commit(); print(f"processed={processed:,} sales={sales:,} snapshots={snapshots:,}", flush=True)
                if args.max_rows and processed >= args.max_rows: break
        if sale_batch: execute_values(cursor, SALE_SQL, sale_batch, page_size=args.batch_size); sales += len(sale_batch)
        if snapshot_batch: execute_values(cursor, SNAPSHOT_SQL, list(snapshot_batch.values()), page_size=args.batch_size); snapshots += len(snapshot_batch)
        raw.commit()
    finally:
        raw.close()
    print(f"complete Illinois declarations={processed:,} sales={sales:,} snapshots={snapshots:,}")


if __name__ == "__main__":
    main()
