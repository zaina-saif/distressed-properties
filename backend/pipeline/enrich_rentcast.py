import argparse
import asyncio
import json
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from app.database.session import engine
from pipeline.providers import RentCastValuationProvider, ValuationResult


def normalize_match_part(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def normalize_street(value: str | None) -> str:
    tokens = re.findall(r"[A-Z0-9]+", (value or "").upper())
    suffixes = {
        "AVENUE": "AVE",
        "BOULEVARD": "BLVD",
        "COURT": "CT",
        "DRIVE": "DR",
        "HIGHWAY": "HWY",
        "LANE": "LN",
        "PLACE": "PL",
        "ROAD": "RD",
        "STREET": "ST",
        "TERRACE": "TER",
        "TURNPIKE": "TPKE",
    }
    return "".join(suffixes.get(token, token) for token in tokens)


def format_optional_currency(value: Any) -> str:
    return f"${value:,.2f}" if value is not None else "Unavailable"


def find_candidate(sheriff_number: str) -> dict[str, Any] | None:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT
                    p.id AS property_id,
                    p.normalized_address,
                    p.street_address,
                    p.city,
                    p.state,
                    p.zip_code,
                    p.unit_number,
                    p.data_quality_score,
                    ss.sheriff_number
                FROM sheriff_sales AS ss
                JOIN properties AS p ON p.id = ss.property_id
                WHERE UPPER(ss.sheriff_number) = UPPER(:sheriff_number)
                LIMIT 1
                """
            ),
            {"sheriff_number": sheriff_number},
        ).mappings().first()

    return dict(row) if row else None


def subject_matches(
    candidate: dict[str, Any],
    result: ValuationResult,
) -> bool:
    return all(
        (
            normalize_street(candidate["street_address"])
            == normalize_street(result.address_line_1),
            normalize_match_part(candidate["city"])
            == normalize_match_part(result.city),
            normalize_match_part(candidate["state"])
            == normalize_match_part(result.state),
            normalize_match_part(candidate["zip_code"])
            == normalize_match_part(result.zip_code),
        )
    )


def save_valuation(property_id: str, result: ValuationResult) -> str:
    valuation_id = str(uuid.uuid4())
    retrieved_at = datetime.now(timezone.utc)

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE property_valuations
                SET is_current = FALSE
                WHERE property_id = :property_id AND is_current = TRUE
                """
            ),
            {"property_id": property_id},
        )
        connection.execute(
            text(
                """
                INSERT INTO property_valuations (
                    id, property_id, provider, provider_property_id,
                    estimated_value, low_value, high_value,
                    provider_response, effective_date, retrieved_at,
                    expires_at, is_current
                ) VALUES (
                    :id, :property_id, :provider, :provider_property_id,
                    :estimated_value, :low_value, :high_value,
                    CAST(:provider_response AS JSONB), :effective_date,
                    :retrieved_at, :expires_at, TRUE
                )
                """
            ),
            {
                "id": valuation_id,
                "property_id": property_id,
                "provider": result.provider,
                "provider_property_id": result.provider_property_id,
                "estimated_value": result.estimated_value,
                "low_value": result.low_value,
                "high_value": result.high_value,
                "provider_response": json.dumps(result.raw_response),
                "effective_date": date.today(),
                "retrieved_at": retrieved_at,
                "expires_at": retrieved_at + timedelta(days=30),
            },
        )

    return valuation_id


async def enrich(sheriff_number: str) -> None:
    candidate = find_candidate(sheriff_number)

    if candidate is None:
        raise RuntimeError("No linked property was found.")
    if candidate["data_quality_score"] < 80:
        raise RuntimeError("Property data quality is too low for a paid lookup.")
    if candidate["unit_number"]:
        raise RuntimeError("Unit properties require manual match validation.")

    provider = RentCastValuationProvider()
    result = await provider.get_valuation(candidate["normalized_address"])

    print(f"Requested: {candidate['normalized_address']}")
    print(f"Matched:   {result.formatted_address}")
    print(f"Estimate:  ${result.estimated_value:,.2f}")
    print(
        "Range:     "
        f"{format_optional_currency(result.low_value)} - "
        f"{format_optional_currency(result.high_value)}"
    )
    print(f"Comparables returned: {result.comparable_count}")

    if not subject_matches(candidate, result):
        raise RuntimeError(
            "RentCast subject address did not match; valuation was not saved."
        )

    valuation_id = save_valuation(str(candidate["property_id"]), result)
    print(f"Saved valuation: {valuation_id}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch and validate one RentCast property valuation."
    )
    parser.add_argument("--sheriff-number", required=True)
    args = parser.parse_args()
    asyncio.run(enrich(args.sheriff_number))


if __name__ == "__main__":
    main()
