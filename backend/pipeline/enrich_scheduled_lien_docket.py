"""Fail-soft public-record enrichment for properties currently in scheduled status.

The collector follows the strategy in IMG_1964: optional city SODA violations,
optional county ArcGIS tax data, and a foreclosure plaintiff fallback.  Source
endpoints are deliberately configuration-driven because SODA and ArcGIS layer
URLs vary by municipality/county.  A missing or blocked source is recorded per
property and never aborts the batch.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from sqlalchemy import text

from app.database.session import engine

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = Path(os.getenv("LIEN_DOCKET_OUTPUT_DIR", ROOT / ".local/enriched-lien-docket"))
PARSER_VERSION = "scheduled-lien-docket-v1"
LOGGER = logging.getLogger("scheduled-lien-docket")

load_dotenv(ROOT / "backend/.env")


def _json_env(name: str) -> dict[str, Any]:
    value = os.getenv(name, "{}").strip()
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        LOGGER.warning("Ignoring invalid %s JSON configuration", name)
        return {}


SODA_ENDPOINTS = _json_env("SODA_ENDPOINTS_JSON")
ARCGIS_ENDPOINTS = _json_env("ARCGIS_TAX_ENDPOINTS_JSON")


def _endpoint(mapping: dict[str, Any], row: dict[str, Any]) -> str | None:
    keys = [
        f"{(row.get('state') or '').upper()}:{(row.get('county') or '').lower()}",
        f"{(row.get('state') or '').upper()}:{(row.get('city') or '').lower()}",
        (row.get("county") or "").lower(),
        (row.get("city") or "").lower(),
        "default",
    ]
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _money(value: Any) -> Decimal | None:
    if value is None:
        return None
    match = re.search(r"-?\$?\s*([\d,]+(?:\.\d{1,2})?)", str(value))
    if not match:
        return None
    try:
        return Decimal(match.group(1).replace(",", ""))
    except InvalidOperation:
        return None


def _number(row: dict[str, Any], names: tuple[str, ...]) -> Decimal | None:
    for key, value in row.items():
        normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
        if any(name in normalized for name in names):
            parsed = _money(value)
            if parsed is not None:
                return parsed
    return None


def _text(row: dict[str, Any], names: tuple[str, ...]) -> str | None:
    for key, value in row.items():
        normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
        if any(name in normalized for name in names) and value not in (None, ""):
            return str(value)
    return None


def _retry_get(client: httpx.Client, url: str, params: dict[str, Any], attempts: int = 4) -> httpx.Response:
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            response = client.get(url, params=params)
            if response.status_code in {429, 500, 502, 503, 504}:
                response.raise_for_status()
            response.raise_for_status()
            return response
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            last = exc
            if attempt == attempts - 1:
                break
            time.sleep(min(2 ** attempt, 8))
    raise RuntimeError(str(last) if last else "request failed")


def query_socrata(client: httpx.Client, row: dict[str, Any]) -> tuple[str, list[dict[str, Any]], str | None]:
    url = _endpoint(SODA_ENDPOINTS, row)
    if not url:
        return "NOT_CONFIGURED", [], None
    address = (row.get("property_address") or "").replace("'", "''")
    parcel = (row.get("parcel_id") or "").replace("'", "''")
    where = f"upper(address) like upper('%{address}%')" if address else ""
    if parcel:
        where = f"({where}) OR upper(parcel_id) = upper('{parcel}')" if where else f"upper(parcel_id) = upper('{parcel}')"
    try:
        params = {"$limit": 5000}
        if where:
            params["$where"] = where
        payload = _retry_get(client, url, params).json()
        rows = payload if isinstance(payload, list) else []
        return "SUCCESS" if rows else "NO_MATCH", [dict(item) for item in rows if isinstance(item, dict)], url
    except Exception as exc:
        return f"FAILED_FETCH:{exc}", [], url


def query_arcgis(client: httpx.Client, row: dict[str, Any]) -> tuple[str, list[dict[str, Any]], str | None]:
    url = _endpoint(ARCGIS_ENDPOINTS, row)
    if not url:
        return "NOT_CONFIGURED", [], None
    if not url.rstrip("/").endswith("/query"):
        url = url.rstrip("/") + "/query"
    parcel = str(row.get("parcel_id") or "").replace("'", "''")
    if not parcel:
        return "MANUAL_REVIEW_REQUIRED:parcel id unavailable", [], url
    try:
        payload = _retry_get(client, url, {
            "where": f"PARCELID='{parcel}'",
            "outFields": "*",
            "returnGeometry": "false",
            "f": "json",
        }).json()
        features = payload.get("features", []) if isinstance(payload, dict) else []
        records = [dict(item.get("attributes") or {}) for item in features if isinstance(item, dict)]
        return "SUCCESS" if records else "NO_MATCH", records, url
    except Exception as exc:
        return f"FAILED_FETCH:{exc}", [], url


def _write_raw(connection, row: dict[str, Any], source_name: str, source_url: str | None, payload: Any, retrieved_at: datetime) -> None:
    raw = {"property": row, "records": payload}
    encoded = json.dumps(raw, sort_keys=True, default=str)
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    connection.execute(text("""
        INSERT INTO raw_public_records(
            property_id, source_name, source_type, source_url, source_record_id,
            search_type, search_query, raw_data, retrieved_at, ingestion_status,
            parser_version, content_hash
        ) VALUES(CAST(:property_id AS UUID), :source_name, :source_type, :source_url,
            :source_record_id, 'ADDRESS_OR_PARCEL', CAST(:search_query AS JSONB),
            CAST(:raw_data AS JSONB), :retrieved_at, 'INGESTED', :parser_version, :content_hash)
        ON CONFLICT(property_id, source_name, content_hash)
        DO UPDATE SET retrieved_at=EXCLUDED.retrieved_at
    """), {
        "property_id": row["property_id"], "source_name": source_name,
        "source_type": "PUBLIC_RECORD_ENRICHMENT", "source_url": source_url,
        "source_record_id": digest[:32], "search_query": json.dumps({"address": row.get("property_address"), "parcel_id": row.get("parcel_id")}),
        "raw_data": encoded, "retrieved_at": retrieved_at, "parser_version": PARSER_VERSION,
        "content_hash": digest,
    })


def _save_enrichment(connection, row: dict[str, Any], result: dict[str, Any], retrieved_at: datetime) -> None:
    connection.execute(text("""
        INSERT INTO public_record_enrichments(
            property_id, status, primary_lender, municipal_violations_count,
            estimated_municipal_debt_usd, outstanding_taxes_usd,
            tax_delinquency_status, source_statuses, source_urls, raw_data,
            error_message, retrieved_at, updated_at
        ) VALUES(CAST(:property_id AS UUID), :status, :primary_lender, :violations,
            :municipal_debt, :taxes, :tax_status, CAST(:source_statuses AS JSONB),
            CAST(:source_urls AS JSONB), CAST(:raw_data AS JSONB), :error_message,
            :retrieved_at, :retrieved_at)
        ON CONFLICT(property_id) DO UPDATE SET
            status=EXCLUDED.status, primary_lender=EXCLUDED.primary_lender,
            municipal_violations_count=EXCLUDED.municipal_violations_count,
            estimated_municipal_debt_usd=EXCLUDED.estimated_municipal_debt_usd,
            outstanding_taxes_usd=EXCLUDED.outstanding_taxes_usd,
            tax_delinquency_status=EXCLUDED.tax_delinquency_status,
            source_statuses=EXCLUDED.source_statuses, source_urls=EXCLUDED.source_urls,
            raw_data=EXCLUDED.raw_data, error_message=EXCLUDED.error_message,
            retrieved_at=EXCLUDED.retrieved_at, updated_at=EXCLUDED.updated_at
    """), {
        "property_id": row["property_id"], "status": result["status"],
        "primary_lender": result.get("primary_lender"), "violations": result.get("municipal_violations_count"),
        "municipal_debt": result.get("estimated_municipal_debt_usd"), "taxes": result.get("outstanding_taxes_usd"),
        "tax_status": result.get("tax_delinquency_status"), "source_statuses": json.dumps(result["source_statuses"]),
        "source_urls": json.dumps(result["source_urls"]), "raw_data": json.dumps(result.get("raw_data", {}), default=str),
        "error_message": result.get("error_message"), "retrieved_at": retrieved_at,
    })


def enrich_row(client: httpx.Client, connection, row: dict[str, Any]) -> dict[str, Any]:
    retrieved_at = datetime.now(timezone.utc)
    soda_status, violations, soda_url = query_socrata(client, row)
    arc_status, taxes, arc_url = query_arcgis(client, row)
    violation_count = len(violations)
    municipal_debt = sum((_number(item, ("amount", "balance", "fine", "penalty", "debt")) or Decimal("0") for item in violations), Decimal("0"))
    tax_amounts = [_number(item, ("balance", "tax", "amount", "delinquent")) for item in taxes]
    tax_amounts = [item for item in tax_amounts if item is not None]
    tax_total = sum(tax_amounts, Decimal("0")) if tax_amounts else None
    tax_status = "Delinquent" if tax_total and tax_total > 0 else ("Paid / no delinquency returned" if taxes else "Unknown")
    primary_lender = row.get("plaintiff") or None
    statuses = {"socrata": soda_status.split(":", 1)[0], "arcgis": arc_status.split(":", 1)[0], "foreclosure_docket": "FALLBACK_EXISTING_SALE_RECORD" if primary_lender else "MANUAL_REVIEW_REQUIRED"}
    urls = [url for url in (soda_url, arc_url, row.get("source_url")) if url]
    errors = [status for status in (soda_status, arc_status) if status.startswith(("FAILED_FETCH", "MANUAL_REVIEW_REQUIRED"))]
    configured = [status for status in (soda_status, arc_status) if status in {"SUCCESS", "NO_MATCH"}]
    if errors:
        overall = "FAILED_FETCH" if all(error.startswith("FAILED_FETCH") for error in errors) else "MANUAL_REVIEW_REQUIRED"
    elif not configured:
        overall = "MANUAL_REVIEW_REQUIRED"
    elif violation_count or tax_total:
        overall = "PARTIAL"
    else:
        overall = "COMPLETED"
    result = {
        "property_id": row["property_id"], "property_address": row.get("property_address"), "county": row.get("county"),
        "status": overall, "primary_lender": primary_lender, "municipal_violations_count": violation_count,
        "estimated_municipal_debt_usd": municipal_debt if violation_count else None, "outstanding_taxes_usd": tax_total,
        "tax_delinquency_status": tax_status, "source_statuses": statuses, "source_urls": urls,
        "raw_data": {"socrata": violations, "arcgis": taxes}, "error_message": "; ".join(errors) if errors else None,
        "retrieved_at": retrieved_at.isoformat(),
    }
    if violations:
        _write_raw(connection, row, "SODA_MUNICIPAL_VIOLATIONS", soda_url, violations, retrieved_at)
    if taxes:
        _write_raw(connection, row, "ARCGIS_TAX_DELINQUENCY", arc_url, taxes, retrieved_at)
    if primary_lender:
        _write_raw(connection, row, "SHERIFF_SALE_FORECLOSURE_DOCKET", row.get("source_url"), {"primary_lender": primary_lender}, retrieved_at)
    _save_enrichment(connection, row, result, retrieved_at)
    return result


def run(limit: int | None = None) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with engine.begin() as connection:
        query = """
            SELECT p.id::text AS property_id, p.normalized_address AS property_address,
                   p.city, p.county, p.state, COALESCE(p.pams_pin, ss.property_number) AS parcel_id,
                   ss.plaintiff, ss.source_url, ss.current_status
            FROM properties p JOIN sheriff_sales ss ON ss.property_id=p.id
            WHERE LOWER(ss.current_status)='scheduled'
            ORDER BY p.id
        """
        if limit:
            query += " LIMIT :limit"
            rows = connection.execute(text(query), {"limit": limit}).mappings().all()
        else:
            rows = connection.execute(text(query)).mappings().all()
        with httpx.Client(timeout=45, follow_redirects=True, headers={"User-Agent": "SheriffSalePublicRecordResearch/1.0"}) as client:
            output_rows = []
            with (OUTPUT / "scheduled_properties.csv").open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else ["property_id"])
                writer.writeheader()
                writer.writerows([dict(row) for row in rows])
            for index, row in enumerate(rows, 1):
                try:
                    result = enrich_row(client, connection, dict(row))
                except Exception as exc:  # fail-soft at the property boundary
                    LOGGER.exception("Property %s failed", row["property_id"])
                    result = {"property_id": row["property_id"], "property_address": row.get("property_address"), "county": row.get("county"), "status": "FAILED_FETCH", "source_statuses": {}, "source_urls": [], "error_message": str(exc), "retrieved_at": datetime.now(timezone.utc).isoformat()}
                    _save_enrichment(connection, dict(row), result, datetime.now(timezone.utc))
                output_rows.append(result)
                if index % 50 == 0 or index == len(rows):
                    LOGGER.info("Processed %s/%s scheduled properties", index, len(rows))
    (OUTPUT / "enriched_lien_docket.json").write_text(json.dumps(output_rows, indent=2, default=str) + "\n")
    if output_rows:
        with (OUTPUT / "enriched_lien_docket.csv").open("w", newline="") as handle:
            fields = sorted({key for item in output_rows for key in item})
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(output_rows)
    print(json.dumps({"processed": len(output_rows), "output": str(OUTPUT), "statuses": {status: sum(1 for item in output_rows if item.get("status") == status) for status in sorted({item.get("status") for item in output_rows})}}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
    run(args.limit)
