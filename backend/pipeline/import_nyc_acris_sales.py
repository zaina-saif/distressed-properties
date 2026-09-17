"""Import NYC ACRIS deed transactions without party/person fields."""
from __future__ import annotations

import argparse
import time
from datetime import date
from decimal import Decimal
from typing import Any, Iterator

import httpx
from psycopg2.extras import execute_values
from sqlalchemy import text

from app.database.session import warehouse_engine
from pipeline.public_property_records import date_value, decimal_value, integer_value, stable_hash, text_value

SOURCE_ID = "nyc_acris_real_property_deeds"
MASTER_PAGE = "https://data.cityofnewyork.us/d/bnx9-e6tj"
LEGALS_PAGE = "https://data.cityofnewyork.us/d/8h5j-fqxa"
MASTER_URL = "https://data.cityofnewyork.us/resource/bnx9-e6tj.json"
LEGALS_URL = "https://data.cityofnewyork.us/resource/8h5j-fqxa.json"
MASTER_FIELDS = ("document_id", "doc_type", "document_date", "document_amt", "recorded_datetime", "percent_trans")
LEGAL_FIELDS = ("document_id", "borough", "block", "lot", "property_type", "street_number", "street_name", "unit")
BOROUGHS = {1: "New York", 2: "Bronx", 3: "Kings", 4: "Queens", 5: "Richmond"}
SALE_COLUMNS = ("source_id", "state", "county", "source_parcel_id", "transaction_id", "sale_date",
                "sale_price", "recording_date", "conveyance_code", "arms_length", "source_hash")
SNAPSHOT_COLUMNS = ("source_id", "state", "county", "source_parcel_id", "snapshot_year", "street_address",
                    "property_type", "land_use_code", "source_hash")
SALE_SQL = f"""INSERT INTO public_property_sales ({','.join(SALE_COLUMNS)}) VALUES %s
ON CONFLICT(source_id,source_parcel_id,transaction_id) DO UPDATE SET sale_date=EXCLUDED.sale_date,
 sale_price=EXCLUDED.sale_price,recording_date=EXCLUDED.recording_date,
 conveyance_code=EXCLUDED.conveyance_code,arms_length=EXCLUDED.arms_length,
 source_hash=EXCLUDED.source_hash,imported_at=NOW()
WHERE public_property_sales.source_hash<>EXCLUDED.source_hash"""
SNAPSHOT_SQL = f"""INSERT INTO public_property_snapshots ({','.join(SNAPSHOT_COLUMNS)}) VALUES %s
ON CONFLICT(source_id,source_parcel_id,snapshot_year) DO UPDATE SET street_address=EXCLUDED.street_address,
 property_type=EXCLUDED.property_type,land_use_code=EXCLUDED.land_use_code,
 source_hash=EXCLUDED.source_hash,imported_at=NOW()
WHERE public_property_snapshots.source_hash<>EXCLUDED.source_hash"""


def bbl(borough: Any, block: Any, lot: Any) -> tuple[str, str] | None:
    borough_number = integer_value(borough)
    block_number = integer_value(block)
    lot_number = integer_value(lot)
    if borough_number not in BOROUGHS or block_number is None or lot_number is None:
        return None
    key = f"{borough_number}{block_number:05d}{lot_number:04d}"
    return f"NYC:BBL:{key}", BOROUGHS[borough_number]


def parse(master: dict[str, Any], legal: dict[str, Any]) -> tuple[tuple[Any, ...], tuple[Any, ...]] | None:
    parcel = bbl(legal.get("borough"), legal.get("block"), legal.get("lot"))
    transaction_id = text_value(master.get("document_id"))
    sale_date = date_value(master.get("document_date"))
    price = decimal_value(master.get("document_amt"))
    if not parcel or not transaction_id or not sale_date or price is None or price <= 0:
        return None
    identity, county = parcel
    document_type = text_value(master.get("doc_type"))
    sale_core = {"source_id": SOURCE_ID, "state": "NY", "county": county,
                 "source_parcel_id": identity, "transaction_id": transaction_id,
                 "sale_date": sale_date, "sale_price": price,
                 "recording_date": date_value(master.get("recorded_datetime")),
                 "conveyance_code": document_type, "arms_length": None}
    address = " ".join(filter(None, (text_value(legal.get("street_number")),
                                      text_value(legal.get("street_name"))))) or None
    property_type = text_value(legal.get("property_type"))
    snapshot_core = {"source_id": SOURCE_ID, "state": "NY", "county": county,
                     "source_parcel_id": identity, "snapshot_year": sale_date.year,
                     "street_address": address, "property_type": property_type,
                     "land_use_code": property_type}
    sale = tuple(sale_core[name] for name in SALE_COLUMNS[:-1]) + (stable_hash(sale_core),)
    snapshot = tuple(snapshot_core[name] for name in SNAPSHOT_COLUMNS[:-1]) + (stable_hash(snapshot_core),)
    return sale, snapshot


def pages(client: httpx.Client, url: str, fields: tuple[str, ...], where: str, size: int) -> Iterator[list[dict[str, Any]]]:
    offset = 0
    while True:
        params = {"$select": ",".join(fields), "$where": where, "$order": ":id", "$limit": size, "$offset": offset}
        for attempt in range(6):
            try:
                response = client.get(url, params=params)
                response.raise_for_status(); rows = response.json(); break
            except (httpx.HTTPError, ValueError):
                if attempt == 5: raise
                time.sleep(2 ** attempt)
        if not rows: break
        yield rows
        offset += len(rows)
        if len(rows) < size: break


def year_bounds(year: int) -> str:
    return f"document_id >= '{year}000000000000' AND document_id < '{year + 1}000000000000'"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", nargs="+", type=int, default=list(range(date.today().year, 2002, -1)))
    parser.add_argument("--page-size", type=int, default=50000)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.dry_run:
        with warehouse_engine.begin() as connection:
            connection.execute(text("""INSERT INTO public_data_sources
              (source_id,state,source_name,source_url,access_method,coverage_notes,last_checked_at)
              VALUES(:id,'NY','NYC ACRIS Real Property Master + Legals',:url,'Socrata API join',
              'Electronic deed transactions linked to BBL; party names excluded; deed type retained and arms-length left unknown',NOW())
              ON CONFLICT(source_id) DO UPDATE SET last_checked_at=NOW(),updated_at=NOW()"""),
                               {"id": SOURCE_ID, "url": MASTER_PAGE})
    raw = warehouse_engine.raw_connection() if not args.dry_run else None
    sales_total = snapshots_total = 0
    try:
        with httpx.Client(timeout=180, follow_redirects=True) as client:
            for year in args.years:
                bounds = year_bounds(year)
                masters = {}
                master_where = f"{bounds} AND doc_type like 'DEED%' AND document_amt > 0"
                for rows in pages(client, MASTER_URL, MASTER_FIELDS, master_where, args.page_size):
                    masters.update((row["document_id"], row) for row in rows)
                sale_batch: dict[tuple[str, str], tuple[Any, ...]] = {}
                snapshot_batch: dict[tuple[str, int], tuple[Any, ...]] = {}
                for rows in pages(client, LEGALS_URL, LEGAL_FIELDS, bounds, args.page_size):
                    for legal in rows:
                        master = masters.get(legal.get("document_id"))
                        if not master: continue
                        parsed = parse(master, legal)
                        if not parsed: continue
                        sale, snapshot = parsed
                        sale_batch[(sale[3], sale[4])] = sale
                        snapshot_batch[(snapshot[3], snapshot[4])] = snapshot
                    if raw is not None and len(sale_batch) >= 10000:
                        cursor = raw.cursor()
                        execute_values(cursor, SALE_SQL, list(sale_batch.values()), page_size=10000)
                        execute_values(cursor, SNAPSHOT_SQL, list(snapshot_batch.values()), page_size=10000)
                        raw.commit(); sales_total += len(sale_batch); snapshots_total += len(snapshot_batch)
                        sale_batch.clear(); snapshot_batch.clear()
                if raw is not None and sale_batch:
                    cursor = raw.cursor()
                    execute_values(cursor, SALE_SQL, list(sale_batch.values()), page_size=10000)
                    execute_values(cursor, SNAPSHOT_SQL, list(snapshot_batch.values()), page_size=10000)
                    raw.commit()
                sales_total += len(sale_batch); snapshots_total += len(snapshot_batch)
                print(f"ACRIS {year}: deed_documents={len(masters):,} total_sales={sales_total:,}", flush=True)
    finally:
        if raw is not None: raw.close()
    print(f"complete dry_run={args.dry_run} ACRIS sales={sales_total:,} snapshots={snapshots_total:,}")


if __name__ == "__main__":
    main()
