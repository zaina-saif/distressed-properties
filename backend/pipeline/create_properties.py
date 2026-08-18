import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.database.session import engine
from pipeline.normalize import (
    NormalizedPropertyAddress,
    normalize_address,
)


REVIEW_OUTPUT_FILE = Path(
    "property_address_manual_review.json"
)


def get_raw_address(
    raw_payload: Any,
) -> Optional[str]:
    """
    Extract the address from the JSON stored by the CivilView loader.
    """

    if raw_payload is None:
        return None

    if isinstance(raw_payload, str):
        try:
            raw_payload = json.loads(raw_payload)
        except json.JSONDecodeError:
            return None

    if not isinstance(raw_payload, dict):
        return None

    # The complete scraped record stores address at the top level.
    top_level_address = raw_payload.get("address")

    if top_level_address:
        return str(top_level_address).strip()

    # Fallback for nested source payload.
    nested_payload = raw_payload.get("raw_payload")

    if isinstance(nested_payload, dict):
        nested_address = nested_payload.get("address")

        if nested_address:
            return str(nested_address).strip()

    return None


def fetch_unlinked_sales(
    connection: Connection,
) -> list[dict[str, Any]]:
    """
    Get sheriff sales that are not yet linked to a property, along
    with the latest available raw CivilView payload.
    """

    result = connection.execute(
        text(
            """
            SELECT
                ss.id AS sheriff_sale_id,
                ss.county,
                ss.sheriff_number,
                ss.current_status,
                ss.current_sale_date,
                raw.raw_payload
            FROM sheriff_sales AS ss
            LEFT JOIN LATERAL (
                SELECT rsr.raw_payload
                FROM raw_scrape_records AS rsr
                WHERE rsr.county = ss.county
                  AND rsr.source_record_id = ss.sheriff_number
                ORDER BY rsr.scraped_at DESC
                LIMIT 1
            ) AS raw ON TRUE
            WHERE ss.property_id IS NULL
            ORDER BY ss.current_sale_date, ss.sheriff_number
            """
        )
    )

    return [dict(row) for row in result.mappings().all()]


def upsert_property(
    connection: Connection,
    address: NormalizedPropertyAddress,
    county: str,
) -> str:
    result = connection.execute(
        text(
            """
            INSERT INTO properties (
                normalized_address,
                street_address,
                unit_number,
                city,
                municipality,
                county,
                state,
                zip_code,
                address_hash,
                data_quality_score,
                created_at,
                updated_at
            )
            VALUES (
                :normalized_address,
                :street_address,
                :unit_number,
                :city,
                :municipality,
                :county,
                :state,
                :zip_code,
                :address_hash,
                :data_quality_score,
                NOW(),
                NOW()
            )
            ON CONFLICT (address_hash)
            DO UPDATE SET
                normalized_address =
                    EXCLUDED.normalized_address,
                street_address =
                    EXCLUDED.street_address,
                unit_number =
                    EXCLUDED.unit_number,
                city =
                    EXCLUDED.city,
                municipality =
                    EXCLUDED.municipality,
                county =
                    EXCLUDED.county,
                state =
                    EXCLUDED.state,
                zip_code =
                    EXCLUDED.zip_code,
                data_quality_score =
                    GREATEST(
                        properties.data_quality_score,
                        EXCLUDED.data_quality_score
                    ),
                updated_at = NOW()
            RETURNING id
            """
        ),
        {
            "normalized_address": address.normalized_address,
            "street_address": address.street_address,
            "unit_number": address.unit_number,
            "city": address.city,
            "municipality": address.city,
            "county": county,
            "state": address.state,
            "zip_code": address.zip_code,
            "address_hash": address.address_hash,
            "data_quality_score": address.data_quality_score,
        },
    )

    property_id = result.scalar_one()
    return str(property_id)


def link_sale_to_property(
    connection: Connection,
    sheriff_sale_id: str,
    property_id: str,
) -> None:
    connection.execute(
        text(
            """
            UPDATE sheriff_sales
            SET
                property_id = :property_id,
                updated_at = NOW()
            WHERE id = :sheriff_sale_id
            """
        ),
        {
            "property_id": property_id,
            "sheriff_sale_id": sheriff_sale_id,
        },
    )


def create_properties() -> None:
    created_or_linked = 0
    failed = 0
    manual_review: list[dict[str, Any]] = []

    with engine.begin() as connection:
        sales = fetch_unlinked_sales(connection)

        print(
            f"Found {len(sales)} unlinked sheriff-sale records."
        )

        for sale in sales:
            sheriff_number = sale["sheriff_number"]
            sheriff_sale_id = str(sale["sheriff_sale_id"])
            county = sale["county"]

            raw_address = get_raw_address(
                sale.get("raw_payload")
            )

            if not raw_address:
                failed += 1

                manual_review.append(
                    {
                        "sheriff_number": sheriff_number,
                        "reason": (
                            "No address was found in the latest "
                            "raw scrape record."
                        ),
                    }
                )

                print(
                    f"Skipped {sheriff_number}: "
                    "address missing"
                )
                continue

            try:
                normalized = normalize_address(raw_address)
            except Exception as exc:
                failed += 1

                manual_review.append(
                    {
                        "sheriff_number": sheriff_number,
                        "original_address": raw_address,
                        "reason": str(exc),
                    }
                )

                print(
                    f"Skipped {sheriff_number}: {exc}"
                )
                continue

            try:
                # A nested transaction acts as a savepoint. One bad
                # record will not cancel all previously processed rows.
                with connection.begin_nested():
                    property_id = upsert_property(
                        connection=connection,
                        address=normalized,
                        county=county,
                    )

                    link_sale_to_property(
                        connection=connection,
                        sheriff_sale_id=sheriff_sale_id,
                        property_id=property_id,
                    )

                created_or_linked += 1

                print(
                    f"Linked {sheriff_number} → "
                    f"{normalized.normalized_address}"
                )

                if normalized.needs_manual_review:
                    manual_review.append(
                        {
                            "sheriff_number": sheriff_number,
                            "property_id": property_id,
                            "original_address": raw_address,
                            "normalized_address": (
                                normalized.normalized_address
                            ),
                            "reason": normalized.review_reason,
                        }
                    )

            except Exception as exc:
                failed += 1

                manual_review.append(
                    {
                        "sheriff_number": sheriff_number,
                        "original_address": raw_address,
                        "reason": (
                            "Database error: "
                            f"{type(exc).__name__}: {exc}"
                        ),
                    }
                )

                print(
                    f"Database error for "
                    f"{sheriff_number}: {exc}"
                )

    REVIEW_OUTPUT_FILE.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(
                    timezone.utc
                ).isoformat(),
                "records": manual_review,
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    print()
    print("Property creation complete.")
    print(f"Created or linked: {created_or_linked}")
    print(f"Failed or skipped: {failed}")
    print(
        "Manual-review report: "
        f"{REVIEW_OUTPUT_FILE.resolve()}"
    )


if __name__ == "__main__":
    create_properties()