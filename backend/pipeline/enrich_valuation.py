import argparse
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import text

from app.database.session import engine


def find_property_by_sheriff_number(
    sheriff_number: str,
) -> dict | None:
    query = text(
        """
        SELECT
            p.id AS property_id,
            p.normalized_address,
            ss.id AS sheriff_sale_id,
            ss.sheriff_number,
            ss.upset_price
        FROM sheriff_sales AS ss
        JOIN properties AS p
            ON p.id = ss.property_id
        WHERE UPPER(ss.sheriff_number) = UPPER(:sheriff_number)
        LIMIT 1
        """
    )

    with engine.connect() as connection:
        result = connection.execute(
            query,
            {"sheriff_number": sheriff_number},
        ).mappings().first()

    return dict(result) if result else None


def save_manual_valuation(
    property_id: str,
    estimated_value: Decimal,
    low_value: Decimal | None = None,
    high_value: Decimal | None = None,
) -> str:
    valuation_id = str(uuid.uuid4())
    retrieved_at = datetime.now(timezone.utc)

    with engine.begin() as connection:
        # Mark prior valuations as no longer current.
        connection.execute(
            text(
                """
                UPDATE property_valuations
                SET is_current = FALSE
                WHERE property_id = :property_id
                  AND is_current = TRUE
                """
            ),
            {"property_id": property_id},
        )

        connection.execute(
            text(
                """
                INSERT INTO property_valuations (
                    id,
                    property_id,
                    provider,
                    estimated_value,
                    low_value,
                    high_value,
                    confidence_score,
                    effective_date,
                    retrieved_at,
                    is_current
                )
                VALUES (
                    :id,
                    :property_id,
                    :provider,
                    :estimated_value,
                    :low_value,
                    :high_value,
                    :confidence_score,
                    :effective_date,
                    :retrieved_at,
                    TRUE
                )
                """
            ),
            {
                "id": valuation_id,
                "property_id": property_id,
                "provider": "manual",
                "estimated_value": estimated_value,
                "low_value": low_value,
                "high_value": high_value,
                "confidence_score": Decimal("0.50"),
                "effective_date": date.today(),
                "retrieved_at": retrieved_at,
            },
        )

    return valuation_id


def parse_decimal(
    value: str | None,
) -> Decimal | None:
    if value is None:
        return None

    cleaned = (
        value.replace("$", "")
        .replace(",", "")
        .strip()
    )

    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(
            f"Invalid dollar amount: {value}"
        ) from exc


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Add a manual property valuation."
    )

    parser.add_argument(
        "--sheriff-number",
        required=True,
    )

    parser.add_argument(
        "--value",
        required=True,
        help="Estimated market value",
    )

    parser.add_argument(
        "--low",
        help="Optional low estimate",
    )

    parser.add_argument(
        "--high",
        help="Optional high estimate",
    )

    args = parser.parse_args()

    property_record = find_property_by_sheriff_number(
        args.sheriff_number
    )

    if property_record is None:
        raise RuntimeError(
            "No linked property was found for sheriff number "
            f"{args.sheriff_number}."
        )

    estimated_value = parse_decimal(args.value)

    if estimated_value is None or estimated_value <= 0:
        raise ValueError(
            "Estimated value must be greater than zero."
        )

    low_value = parse_decimal(args.low)
    high_value = parse_decimal(args.high)

    valuation_id = save_manual_valuation(
        property_id=str(property_record["property_id"]),
        estimated_value=estimated_value,
        low_value=low_value,
        high_value=high_value,
    )

    print()
    print("Valuation saved successfully.")
    print(
        f"Property: {property_record['normalized_address']}"
    )
    print(
        f"Sheriff number: "
        f"{property_record['sheriff_number']}"
    )
    print(f"Estimated value: ${estimated_value:,.2f}")
    print(f"Valuation ID: {valuation_id}")


if __name__ == "__main__":
    main()
