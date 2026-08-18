import csv
import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.database.session import engine


CSV_FILE = Path("property_analysis_input.csv")
CALCULATION_VERSION = "equity-csv-v1"


def parse_decimal(
    value: str | None,
    *,
    field_name: str,
    required: bool = False,
) -> Decimal | None:
    """
    Convert a CSV dollar value into a Decimal.

    Accepts values such as:
        650000
        650,000
        $650,000.00
    """

    if value is None or not value.strip():
        if required:
            raise ValueError(
                f"{field_name} is required."
            )

        return None

    cleaned = (
        value.replace("$", "")
        .replace(",", "")
        .strip()
    )

    try:
        amount = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(
            f"Invalid {field_name}: {value!r}"
        ) from exc

    if amount < 0:
        raise ValueError(
            f"{field_name} cannot be negative."
        )

    return amount


def load_csv_rows() -> list[dict[str, str]]:
    """
    Read and validate the property-analysis CSV file.
    """

    if not CSV_FILE.exists():
        raise FileNotFoundError(
            f"{CSV_FILE} was not found.\n"
            "Create it inside the backend folder before "
            "running this script."
        )

    with CSV_FILE.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as csv_file:
        reader = csv.DictReader(csv_file)

        if reader.fieldnames is None:
            raise ValueError(
                "The CSV file does not contain a header row."
            )

        required_columns = {
            "sheriff_number",
            "estimated_value",
            "upset_price",
        }

        missing_columns = (
            required_columns - set(reader.fieldnames)
        )

        if missing_columns:
            raise ValueError(
                "The CSV is missing required columns: "
                + ", ".join(sorted(missing_columns))
            )

        return [
            {
                key: value.strip()
                if isinstance(value, str)
                else value
                for key, value in row.items()
            }
            for row in reader
            if any(
                isinstance(value, str) and value.strip()
                for value in row.values()
            )
        ]


def find_sale(
    connection: Connection,
    sheriff_number: str,
) -> dict[str, Any] | None:
    """
    Find the sheriff sale and its linked property.
    """

    result = connection.execute(
        text(
            """
            SELECT
                ss.id AS sheriff_sale_id,
                ss.sheriff_number,
                ss.property_id,
                ss.upset_price AS existing_upset_price,
                p.normalized_address
            FROM sheriff_sales AS ss
            LEFT JOIN properties AS p
                ON p.id = ss.property_id
            WHERE UPPER(ss.sheriff_number) =
                  UPPER(:sheriff_number)
            LIMIT 1
            """
        ),
        {
            "sheriff_number": sheriff_number,
        },
    ).mappings().first()

    return dict(result) if result else None


def save_valuation(
    connection: Connection,
    *,
    property_id: str,
    estimated_value: Decimal,
    low_value: Decimal | None,
    high_value: Decimal | None,
) -> str:
    """
    Mark previous valuations inactive and insert a new current
    manual CSV valuation.
    """

    connection.execute(
        text(
            """
            UPDATE property_valuations
            SET is_current = FALSE
            WHERE property_id = :property_id
              AND is_current = TRUE
            """
        ),
        {
            "property_id": property_id,
        },
    )

    valuation_id = str(uuid.uuid4())

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
            "provider": "manual_csv",
            "estimated_value": estimated_value,
            "low_value": low_value,
            "high_value": high_value,
            "confidence_score": Decimal("0.50"),
            "effective_date": date.today(),
            "retrieved_at": datetime.now(
                timezone.utc
            ),
        },
    )

    return valuation_id


def update_upset_price(
    connection: Connection,
    *,
    sheriff_sale_id: str,
    upset_price: Decimal,
) -> None:
    connection.execute(
        text(
            """
            UPDATE sheriff_sales
            SET
                upset_price = :upset_price,
                updated_at = NOW()
            WHERE id = :sheriff_sale_id
            """
        ),
        {
            "sheriff_sale_id": sheriff_sale_id,
            "upset_price": upset_price,
        },
    )


def save_analysis(
    connection: Connection,
    *,
    sheriff_sale_id: str,
    valuation_id: str,
    market_value: Decimal,
    upset_price: Decimal,
    repairs: Decimal,
    closing_costs: Decimal,
    holding_costs: Decimal,
    surviving_liens: Decimal,
) -> str:
    """
    Calculate and save gross and net equity.
    """

    gross_equity = market_value - upset_price

    gross_equity_percent = (
        gross_equity / market_value
        if market_value > 0
        else None
    )

    estimated_net_equity = (
        market_value
        - upset_price
        - repairs
        - closing_costs
        - holding_costs
        - surviving_liens
    )

    estimated_net_equity_percent = (
        estimated_net_equity / market_value
        if market_value > 0
        else None
    )

    # This version does not include a separate desired-profit
    # deduction. It represents the maximum bid before profit.
    maximum_recommended_bid = (
        market_value
        - repairs
        - closing_costs
        - holding_costs
        - surviving_liens
    )

    assumptions = {
        "source": "property_analysis_input.csv",
        "estimated_repairs": str(repairs),
        "closing_costs": str(closing_costs),
        "holding_costs": str(holding_costs),
        "surviving_liens": str(surviving_liens),
    }

    analysis_id = str(uuid.uuid4())

    result = connection.execute(
        text(
            """
            INSERT INTO property_analyses (
                id,
                sheriff_sale_id,
                valuation_id,
                market_value,
                upset_price,
                gross_equity,
                gross_equity_percent,
                surviving_lien_total,
                estimated_repairs,
                closing_costs,
                holding_costs,
                estimated_net_equity,
                estimated_net_equity_percent,
                maximum_recommended_bid,
                calculation_version,
                assumptions,
                calculated_at
            )
            VALUES (
                :id,
                :sheriff_sale_id,
                :valuation_id,
                :market_value,
                :upset_price,
                :gross_equity,
                :gross_equity_percent,
                :surviving_lien_total,
                :estimated_repairs,
                :closing_costs,
                :holding_costs,
                :estimated_net_equity,
                :estimated_net_equity_percent,
                :maximum_recommended_bid,
                :calculation_version,
                CAST(:assumptions AS JSONB),
                :calculated_at
            )
            ON CONFLICT (
                sheriff_sale_id,
                calculation_version
            )
            DO UPDATE SET
                valuation_id =
                    EXCLUDED.valuation_id,
                market_value =
                    EXCLUDED.market_value,
                upset_price =
                    EXCLUDED.upset_price,
                gross_equity =
                    EXCLUDED.gross_equity,
                gross_equity_percent =
                    EXCLUDED.gross_equity_percent,
                surviving_lien_total =
                    EXCLUDED.surviving_lien_total,
                estimated_repairs =
                    EXCLUDED.estimated_repairs,
                closing_costs =
                    EXCLUDED.closing_costs,
                holding_costs =
                    EXCLUDED.holding_costs,
                estimated_net_equity =
                    EXCLUDED.estimated_net_equity,
                estimated_net_equity_percent =
                    EXCLUDED.estimated_net_equity_percent,
                maximum_recommended_bid =
                    EXCLUDED.maximum_recommended_bid,
                assumptions =
                    EXCLUDED.assumptions,
                calculated_at =
                    EXCLUDED.calculated_at
            RETURNING id
            """
        ),
        {
            "id": analysis_id,
            "sheriff_sale_id": sheriff_sale_id,
            "valuation_id": valuation_id,
            "market_value": market_value,
            "upset_price": upset_price,
            "gross_equity": gross_equity,
            "gross_equity_percent": (
                gross_equity_percent
            ),
            "surviving_lien_total": (
                surviving_liens
            ),
            "estimated_repairs": repairs,
            "closing_costs": closing_costs,
            "holding_costs": holding_costs,
            "estimated_net_equity": (
                estimated_net_equity
            ),
            "estimated_net_equity_percent": (
                estimated_net_equity_percent
            ),
            "maximum_recommended_bid": (
                maximum_recommended_bid
            ),
            "calculation_version": (
                CALCULATION_VERSION
            ),
            "assumptions": json.dumps(
                assumptions
            ),
            "calculated_at": datetime.now(
                timezone.utc
            ),
        },
    )

    return str(result.scalar_one())


def process_row(
    connection: Connection,
    row: dict[str, str],
    row_number: int,
) -> dict[str, Any]:
    sheriff_number = (
        row.get("sheriff_number", "")
        .strip()
        .upper()
    )

    if not sheriff_number:
        raise ValueError(
            f"Row {row_number}: sheriff_number is missing."
        )

    estimated_value = parse_decimal(
        row.get("estimated_value"),
        field_name="estimated_value",
        required=True,
    )

    upset_price = parse_decimal(
        row.get("upset_price"),
        field_name="upset_price",
        required=True,
    )

    low_value = parse_decimal(
        row.get("low_value"),
        field_name="low_value",
    )

    high_value = parse_decimal(
        row.get("high_value"),
        field_name="high_value",
    )

    repairs = (
        parse_decimal(
            row.get("repairs"),
            field_name="repairs",
        )
        or Decimal("0")
    )

    closing_costs = (
        parse_decimal(
            row.get("closing_costs"),
            field_name="closing_costs",
        )
        or Decimal("0")
    )

    holding_costs = (
        parse_decimal(
            row.get("holding_costs"),
            field_name="holding_costs",
        )
        or Decimal("0")
    )

    surviving_liens = (
        parse_decimal(
            row.get("surviving_liens"),
            field_name="surviving_liens",
        )
        or Decimal("0")
    )

    if estimated_value is None:
        raise ValueError(
            f"Row {row_number}: estimated_value is missing."
        )

    if upset_price is None:
        raise ValueError(
            f"Row {row_number}: upset_price is missing."
        )

    sale = find_sale(
        connection,
        sheriff_number,
    )

    if sale is None:
        raise ValueError(
            f"Row {row_number}: sheriff sale "
            f"{sheriff_number} was not found."
        )

    if sale["property_id"] is None:
        raise ValueError(
            f"Row {row_number}: sheriff sale "
            f"{sheriff_number} is not linked to a property."
        )

    valuation_id = save_valuation(
        connection,
        property_id=str(sale["property_id"]),
        estimated_value=estimated_value,
        low_value=low_value,
        high_value=high_value,
    )

    update_upset_price(
        connection,
        sheriff_sale_id=str(
            sale["sheriff_sale_id"]
        ),
        upset_price=upset_price,
    )

    analysis_id = save_analysis(
        connection,
        sheriff_sale_id=str(
            sale["sheriff_sale_id"]
        ),
        valuation_id=valuation_id,
        market_value=estimated_value,
        upset_price=upset_price,
        repairs=repairs,
        closing_costs=closing_costs,
        holding_costs=holding_costs,
        surviving_liens=surviving_liens,
    )

    gross_equity = (
        estimated_value - upset_price
    )

    return {
        "sheriff_number": sheriff_number,
        "address": sale["normalized_address"],
        "valuation_id": valuation_id,
        "analysis_id": analysis_id,
        "market_value": estimated_value,
        "upset_price": upset_price,
        "gross_equity": gross_equity,
    }


def import_property_analysis_csv() -> None:
    rows = load_csv_rows()

    if not rows:
        print("The CSV contains no data rows.")
        return

    succeeded = 0
    failed = 0
    failures: list[dict[str, Any]] = []

    print(f"Found {len(rows)} CSV data rows.")
    print()

    with engine.begin() as connection:
        for row_number, row in enumerate(
            rows,
            start=2,
        ):
            sheriff_number = (
                row.get("sheriff_number")
                or "unknown"
            )

            try:
                # A savepoint prevents one bad CSV row from
                # cancelling all successful rows.
                with connection.begin_nested():
                    result = process_row(
                        connection,
                        row,
                        row_number,
                    )

                succeeded += 1

                print(
                    f"Imported {result['sheriff_number']} | "
                    f"market=${result['market_value']:,.2f} | "
                    f"upset=${result['upset_price']:,.2f} | "
                    f"equity=${result['gross_equity']:,.2f}"
                )

            except Exception as exc:
                failed += 1

                failure = {
                    "row_number": row_number,
                    "sheriff_number": sheriff_number,
                    "error": (
                        f"{type(exc).__name__}: {exc}"
                    ),
                }

                failures.append(failure)

                print(
                    f"Failed row {row_number} "
                    f"({sheriff_number}): {exc}"
                )

    failure_file = Path(
        "property_analysis_import_failures.json"
    )

    failure_file.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(
                    timezone.utc
                ).isoformat(),
                "failures": failures,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print()
    print("CSV property-analysis import complete.")
    print(f"Succeeded: {succeeded}")
    print(f"Failed: {failed}")

    if failures:
        print(
            "Failure report: "
            f"{failure_file.resolve()}"
        )


if __name__ == "__main__":
    import_property_analysis_csv()