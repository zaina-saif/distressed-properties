import argparse
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import text

from app.database.session import engine


CALCULATION_VERSION = "equity-v1"


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


def get_sale_data(
    sheriff_number: str,
) -> dict | None:
    query = text(
        """
        SELECT
            ss.id AS sheriff_sale_id,
            ss.sheriff_number,
            ss.upset_price,
            p.id AS property_id,
            p.normalized_address,
            pv.id AS valuation_id,
            pv.estimated_value AS market_value
        FROM sheriff_sales AS ss
        JOIN properties AS p
            ON p.id = ss.property_id
        LEFT JOIN LATERAL (
            SELECT *
            FROM property_valuations
            WHERE property_id = p.id
              AND is_current = TRUE
            ORDER BY retrieved_at DESC
            LIMIT 1
        ) AS pv ON TRUE
        WHERE UPPER(ss.sheriff_number) =
              UPPER(:sheriff_number)
        LIMIT 1
        """
    )

    with engine.connect() as connection:
        result = connection.execute(
            query,
            {"sheriff_number": sheriff_number},
        ).mappings().first()

    return dict(result) if result else None


def update_upset_price(
    sheriff_sale_id: str,
    upset_price: Decimal,
) -> None:
    with engine.begin() as connection:
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


def calculate_and_save_analysis(
    sale_data: dict,
    upset_price: Decimal,
    estimated_repairs: Decimal,
    closing_costs: Decimal,
    holding_costs: Decimal,
    surviving_liens: Decimal,
) -> str:
    market_value = Decimal(
        str(sale_data["market_value"])
    )

    gross_equity = market_value - upset_price

    gross_equity_percent = (
        gross_equity / market_value
        if market_value > 0
        else None
    )

    estimated_net_equity = (
        market_value
        - upset_price
        - estimated_repairs
        - closing_costs
        - holding_costs
        - surviving_liens
    )

    estimated_net_equity_percent = (
        estimated_net_equity / market_value
        if market_value > 0
        else None
    )

    maximum_recommended_bid = (
        market_value
        - estimated_repairs
        - closing_costs
        - holding_costs
        - surviving_liens
    )

    analysis_id = str(uuid.uuid4())

    assumptions = {
        "estimated_repairs": str(estimated_repairs),
        "closing_costs": str(closing_costs),
        "holding_costs": str(holding_costs),
        "surviving_liens": str(surviving_liens),
    }

    with engine.begin() as connection:
        connection.execute(
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
                    valuation_id = EXCLUDED.valuation_id,
                    market_value = EXCLUDED.market_value,
                    upset_price = EXCLUDED.upset_price,
                    gross_equity = EXCLUDED.gross_equity,
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
                    assumptions = EXCLUDED.assumptions,
                    calculated_at = EXCLUDED.calculated_at
                RETURNING id
                """
            ),
            {
                "id": analysis_id,
                "sheriff_sale_id": sale_data[
                    "sheriff_sale_id"
                ],
                "valuation_id": sale_data["valuation_id"],
                "market_value": market_value,
                "upset_price": upset_price,
                "gross_equity": gross_equity,
                "gross_equity_percent": (
                    gross_equity_percent
                ),
                "surviving_lien_total": surviving_liens,
                "estimated_repairs": estimated_repairs,
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
                "assumptions": json.dumps(assumptions),
                "calculated_at": datetime.now(
                    timezone.utc
                ),
            },
        )

    return analysis_id


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Calculate property equity."
    )

    parser.add_argument(
        "--sheriff-number",
        required=True,
    )

    parser.add_argument(
        "--upset-price",
        help=(
            "Optional upset price. If supplied, it is also "
            "saved to sheriff_sales."
        ),
    )

    parser.add_argument(
        "--repairs",
        default="0",
    )

    parser.add_argument(
        "--closing-costs",
        default="0",
    )

    parser.add_argument(
        "--holding-costs",
        default="0",
    )

    parser.add_argument(
        "--surviving-liens",
        default="0",
    )

    args = parser.parse_args()

    sale_data = get_sale_data(args.sheriff_number)

    if sale_data is None:
        raise RuntimeError(
            "Sheriff sale or linked property not found."
        )

    if sale_data["market_value"] is None:
        raise RuntimeError(
            "No current valuation exists. Run "
            "pipeline.enrich_valuation first."
        )

    provided_upset_price = parse_decimal(
        args.upset_price
    )

    database_upset_price = (
        Decimal(str(sale_data["upset_price"]))
        if sale_data["upset_price"] is not None
        else None
    )

    upset_price = (
        provided_upset_price
        if provided_upset_price is not None
        else database_upset_price
    )

    if upset_price is None:
        raise RuntimeError(
            "No upset price is available. Supply one using "
            "--upset-price."
        )

    if provided_upset_price is not None:
        update_upset_price(
            sheriff_sale_id=str(
                sale_data["sheriff_sale_id"]
            ),
            upset_price=provided_upset_price,
        )

    estimated_repairs = (
        parse_decimal(args.repairs) or Decimal("0")
    )

    closing_costs = (
        parse_decimal(args.closing_costs)
        or Decimal("0")
    )

    holding_costs = (
        parse_decimal(args.holding_costs)
        or Decimal("0")
    )

    surviving_liens = (
        parse_decimal(args.surviving_liens)
        or Decimal("0")
    )

    analysis_id = calculate_and_save_analysis(
        sale_data=sale_data,
        upset_price=upset_price,
        estimated_repairs=estimated_repairs,
        closing_costs=closing_costs,
        holding_costs=holding_costs,
        surviving_liens=surviving_liens,
    )

    market_value = Decimal(
        str(sale_data["market_value"])
    )

    gross_equity = market_value - upset_price

    print()
    print("Equity analysis saved successfully.")
    print(
        f"Property: {sale_data['normalized_address']}"
    )
    print(f"Market value: ${market_value:,.2f}")
    print(f"Upset price: ${upset_price:,.2f}")
    print(f"Gross equity: ${gross_equity:,.2f}")
    print(f"Analysis ID: {analysis_id}")


if __name__ == "__main__":
    main()