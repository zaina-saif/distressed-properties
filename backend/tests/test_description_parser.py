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


def test_extracts_notice_lot_and_block_without_boilerplate_false_match() -> None:
    result = parse_sale_description(
        "Lot Block Number if available: Lot and Block: Lot 95, Block 153 "
        "Tax Map of Township of Marlboro COMMONLY KNOWN AS: 107 Reids Hill Road"
    )
    assert result.block == "153"
    assert result.lot == "95"
    assert result.parcel_identifiers == [{"lot": "95", "block": "153", "qualifier": None}]


def test_extracts_repeated_multi_parcel_clause() -> None:
    result = parse_sale_description(
        "Lot Block Number if available: Lot 14 in Block 28 and Lot 15 in Block 28 "
        "Tax Map of Borough of Keansburg"
    )
    assert result.block is None and result.lot is None
    assert result.parcel_identifiers == [
        {"lot": "14", "block": "28", "qualifier": None},
        {"lot": "15", "block": "28", "qualifier": None},
    ]


def test_extracts_shared_block_multiple_lots() -> None:
    result = parse_sale_description(
        "Lot Block Number if available: Lot(s) 6 and 7.01, Block 184 "
        "Tax Map of Borough of Union Beach"
    )
    assert result.parcel_identifiers == [
        {"lot": "6", "block": "184", "qualifier": None},
        {"lot": "7.01", "block": "184", "qualifier": None},
    ]


def test_extracts_condominium_qualifier() -> None:
    result = parse_sale_description(
        "Lot Block Number if available: Lot and Block: Lot(s) 3.03 C05-6, Block 10, "
        "Tax Map of Township of Manalapan"
    )
    assert result.parcel_identifiers == [
        {"lot": "3.03", "block": "10", "qualifier": "C05-6"}
    ]


def test_extracts_repeated_renumbered_tax_parcels() -> None:
    result = parse_sale_description(
        "2000 Avenue of Memories Tax Block 110 n/k/a Tax Block 110.20, Tax Lot 1 "
        "on the Official Tax Map. 2200 Avenue of Memories Tax Block 110 n/k/a "
        "Tax Block 110.21, Tax Lot 1 on the Official Tax Map."
    )
    assert result.parcel_identifiers == [
        {"block": "110.20", "lot": "1", "qualifier": None},
        {"block": "110.21", "lot": "1", "qualifier": None},
    ]
