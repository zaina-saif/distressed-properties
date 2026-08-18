from decimal import Decimal

from pipeline.parse_sale_description import parse_sale_description


def test_parse_sale_description_extracts_core_fields() -> None:
    sample = """
    The estimated upset amount for the scheduled sheriff's sale
    is currently $663,061.99.

    The approximate judgment amount is $620,450.25, together with
    interest accruing at $54.30 per day.

    The property is owner occupied. A deposit of 20% is required,
    and the remaining balance is due within 30 days.

    Docket No. F-012345-25.
    Block 120, Lot 14.02.
    """

    result = parse_sale_description(sample)

    assert result.estimated_upset_price == Decimal("663061.99")
    assert result.judgment_amount == Decimal("620450.25")
    assert result.daily_interest == Decimal("54.30")
    assert result.deposit_percent == Decimal("20")
    assert result.balance_due_days == 30
    assert result.owner_occupied is True
    assert result.docket_number == "F-012345-25"
    assert result.block == "120"
    assert result.lot == "14.02"


def test_parse_sale_description_handles_vacancy() -> None:
    result = parse_sale_description("The premises are vacant.")

    assert result.owner_occupied is False


def test_estimated_upset_bid_does_not_capture_square_footage() -> None:
    result = parse_sale_description(
        "Estimated Upset Bid Amount: $175,000.00. "
        "The upset amount includes the tax escrow. "
        "The house is 1594 square feet, built in 2009."
    )

    assert result.estimated_upset_price == Decimal("175000.00")
    assert result.alternate_upset_price is None


def test_money_parser_accepts_spacing_after_comma() -> None:
    result = parse_sale_description(
        "Upset Amount: $15, 501.09. Status: Owner occupied."
    )

    assert result.alternate_upset_price == Decimal("15501.09")
