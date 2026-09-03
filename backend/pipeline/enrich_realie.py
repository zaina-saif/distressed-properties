"""Fetch validated Realie AVMs for linked sheriff-sale properties."""

import argparse
import asyncio
import json
import os
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import text

from app.database.session import engine


BASE_URL = "https://app.realie.ai/api/public/property/address/"


def normalized(value: str | None) -> str:
    suffixes = {
        "AVENUE": "AVE", "BOULEVARD": "BLVD", "COURT": "CT",
        "DRIVE": "DR", "HIGHWAY": "HWY", "LANE": "LN", "PLACE": "PL",
        "ROAD": "RD", "STREET": "ST", "TERRACE": "TER", "TURNPIKE": "TPKE",
    }
    tokens = re.findall(r"[A-Z0-9]+", (value or "").upper())
    return "".join(suffixes.get(token, token) for token in tokens)


def candidates(state: str, county: str, pending_only: bool) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        rows = connection.execute(text("""
            SELECT DISTINCT ON (p.id) p.id AS property_id, p.street_address,
                p.city, p.state, p.zip_code, p.unit_number
            FROM sheriff_sales AS ss
            JOIN properties AS p ON p.id = ss.property_id
            WHERE UPPER(ss.state) = UPPER(:state)
              AND UPPER(ss.county) = UPPER(:county)
              AND (
                  NOT :pending_only OR NOT EXISTS (
                      SELECT 1 FROM property_valuations AS pv
                      WHERE pv.property_id = p.id
                        AND pv.provider = 'realie' AND pv.is_current = TRUE
                  )
              )
            ORDER BY p.id, ss.current_sale_date DESC NULLS LAST
        """), {
            "state": state, "county": county, "pending_only": pending_only,
        }).mappings().all()
    return [dict(row) for row in rows]


def extract_result(candidate: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    prop = payload.get("property") or {}
    location = prop.get("propertyLocation") or {}
    valuations = prop.get("realieValuation") or {}
    ml = valuations.get("ml") or {}
    comp = valuations.get("comp") or {}
    requested_street = normalized(candidate["street_address"])
    matched_street = normalized(location.get("addressLine1") or location.get("address"))
    requested_zip = normalized(candidate["zip_code"])
    matched_zip = normalized(location.get("zipCode"))
    if not requested_street or requested_street != matched_street:
        raise ValueError("returned street address did not match")
    if requested_zip and matched_zip and requested_zip != matched_zip:
        raise ValueError("returned ZIP code did not match")
    valuation = ml if ml.get("value") is not None else comp
    method = "ml" if ml.get("value") is not None else "comp"
    if valuation.get("value") is None:
        raise ValueError("matched property has no Realie valuation")
    return {
        "provider_property_id": prop.get("realieParcelId") or prop.get("parcelId"),
        "estimated_value": Decimal(str(valuation["value"])),
        "low_value": Decimal(str(valuation["low"])) if valuation.get("low") is not None else None,
        "high_value": Decimal(str(valuation["high"])) if valuation.get("high") is not None else None,
        "valuation_method": method,
        "comparable_value": comp.get("value"),
        "matched_address": location.get("addressFullUSPS") or location.get("addressFull"),
        "raw_response": payload,
    }


def save(property_id: str, result: dict[str, Any]) -> None:
    now = datetime.now(timezone.utc)
    with engine.begin() as connection:
        connection.execute(text("""
            UPDATE property_valuations SET is_current=FALSE
            WHERE property_id=:property_id AND is_current=TRUE
        """), {"property_id": property_id})
        connection.execute(text("""
            INSERT INTO property_valuations (
                id, property_id, provider, provider_property_id,
                estimated_value, low_value, high_value, provider_response,
                effective_date, retrieved_at, expires_at, is_current
            ) VALUES (
                :id, :property_id, 'realie', :provider_property_id,
                :estimated_value, :low_value, :high_value,
                CAST(:provider_response AS JSONB), :effective_date,
                :retrieved_at, :expires_at, TRUE
            )
        """), {
            "id": str(uuid.uuid4()), "property_id": property_id,
            "provider_property_id": result["provider_property_id"],
            "valuation_method": result["valuation_method"],
            "estimated_value": result["estimated_value"],
            "low_value": result["low_value"], "high_value": result["high_value"],
            "provider_response": json.dumps(result["raw_response"]),
            "effective_date": date.today(), "retrieved_at": now,
            "expires_at": now + timedelta(days=30),
        })


async def fetch_one(client: httpx.AsyncClient, semaphore: asyncio.Semaphore,
                    candidate: dict[str, Any], state: str, county: str):
    base_params = {"state": state, "county": county.upper(), "address": candidate["street_address"]}
    if candidate.get("unit_number"):
        base_params["unitNumberStripped"] = candidate["unit_number"]
    strategies = [base_params, {**base_params, "city": candidate["city"]}]
    async with semaphore:
        last_error = "not_found"
        for params in strategies:
            for attempt in range(3):
                try:
                    response = await client.get(BASE_URL, params=params)
                    if response.status_code == 404:
                        last_error = "not_found"
                        break
                    if response.status_code == 429 or response.status_code >= 500:
                        if attempt < 2:
                            await asyncio.sleep(2 ** attempt)
                            continue
                    response.raise_for_status()
                    try:
                        return candidate, extract_result(candidate, response.json()), None
                    except (ValueError, KeyError) as exc:
                        last_error = str(exc)
                        break
                except httpx.HTTPError as exc:
                    last_error = str(exc)
                    if attempt < 2:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    break
        return candidate, None, last_error
    return candidate, None, "request_failed"


async def enrich(state: str, county: str, concurrency: int, output: str | None,
                 pending_only: bool) -> None:
    api_key = os.getenv("REALIE_API_KEY")
    if not api_key:
        raise RuntimeError("REALIE_API_KEY is required")
    rows = candidates(state, county, pending_only)
    print(f"Realie candidates: {len(rows)}")
    semaphore = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(headers={"Authorization": api_key}, timeout=45) as client:
        results = await asyncio.gather(
            *(fetch_one(client, semaphore, row, state, county) for row in rows)
        )

    saved = 0
    failures: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    for candidate, result, error in results:
        if result is None:
            failures.append({
                "property_id": str(candidate["property_id"]), "address": candidate["street_address"],
                "city": candidate["city"], "zip_code": candidate["zip_code"], "error": error,
            })
            continue
        save(str(candidate["property_id"]), result)
        saved += 1
        audit.append({
            "property_id": str(candidate["property_id"]),
            "requested_address": candidate["street_address"],
            "matched_address": result["matched_address"],
            "provider_property_id": result["provider_property_id"],
            "estimated_value": float(result["estimated_value"]),
            "low_value": float(result["low_value"]) if result["low_value"] is not None else None,
            "high_value": float(result["high_value"]) if result["high_value"] is not None else None,
            "comparable_value": result["comparable_value"],
        })
    if output:
        with open(output, "w", encoding="utf-8") as handle:
            json.dump({"valuations": audit, "failures": failures}, handle, indent=2)
    print(f"Realie valuations saved: {saved}")
    print(f"Unmatched or unavailable: {len(failures)}")
    counts: dict[str, int] = {}
    for failure in failures:
        counts[failure["error"]] = counts.get(failure["error"], 0) + 1
    for reason, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        print(f"  {count}: {reason}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch and save validated Realie AVMs by county.")
    parser.add_argument("--state", default="NJ")
    parser.add_argument("--county", required=True)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--output")
    parser.add_argument("--pending-only", action="store_true")
    args = parser.parse_args()
    asyncio.run(enrich(args.state, args.county, args.concurrency, args.output, args.pending_only))


if __name__ == "__main__":
    main()
