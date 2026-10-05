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


def test_extracts_estimated_upset_sheriffs_bid_amount() -> None:
    result = parse_sale_description(
        "Estimated Upset Sheriff’s Bid Amount: $490,000.00, "
        "subject to any additional sums ordered by the court."
    )

    assert result.estimated_upset_price == Decimal("490000.00")
    assert result.alternate_upset_price is None


def test_extracts_common_civilview_upset_wording_variants() -> None:
    samples = {
        "The Plaintiff's Upset Bid Amount Presently Approximates $185,000.00": "185000.00",
        "Estimated upset Sheriff's Sale Bid Amount $2,322,000.00": "2322000.00",
        "Good Faith Estimated Upset: $88,996.77": "88996.77",
        "The approximate upset sum is $485,621.62": "485621.62",
        "The approximate sheriff upset is $68,000.00": "68000.00",
        "Plaintiff's upset bid is $381,935.09": "381935.09",
        "Upset Bid Amount: $423,625.45": "423625.45",
        "Upset price: Approximately any: $502,000.00": "502000.00",
    }

    for description, expected in samples.items():
        result = parse_sale_description(description)
        amount = result.estimated_upset_price or result.alternate_upset_price
        assert amount == Decimal(expected)


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


def test_civilview_structured_upset_and_judgment_labels():
    from pipeline.parse_sale_description import parse_sale_description

    camden = parse_sale_description("Address:\n14 CHAPEL CIRCLE\nApprox. Upset*:\n$112,977.80\nAttorney:\nX\n*Excludes Judgment Interest and Sheriff Fees.")
    assert str(camden.alternate_upset_price) == "112977.80"
    assert camden.judgment_amount is None

    hudson = parse_sale_description("Judgment:\n$656,519.32\nGood Faith Upset*:\n$700,100.00\nAttorney:\nX")
    assert str(hudson.judgment_amount) == "656519.32"
    assert str(hudson.estimated_upset_price) == "700100.00"

    cape_may = parse_sale_description("Approx. Judgment*:\n$159,883.61\nMinimum Bid:\n$174,053.01\nAttorney:")
    assert str(cape_may.judgment_amount) == "159883.61"
    assert str(cape_may.alternate_upset_price) == "174053.01"


def test_structured_labels_need_an_adjacent_amount():
    from pipeline.parse_sale_description import parse_sale_description

    parsed = parse_sale_description("Approx. Upset*:\nAttorney:\nSmith LLC\nPhone 1-856-813-1700")

    assert parsed.alternate_upset_price is None


def test_dates_and_malformed_figures_are_not_money():
    from pipeline.parse_sale_description import parse_sale_description

    as_of = parse_sale_description("The Good Faith Estimate of the Upset Bid Amount as of 6/5/2026 is $254,045.67 PREMISES")
    assert str(as_of.alternate_upset_price or as_of.estimated_upset_price) == "254045.67"

    spaced = parse_sale_description("Estimated Upset Sheriff's Sale Bid Amount: $441 ,000.00 Subject to")
    assert str(spaced.estimated_upset_price) == "441000.00"

    malformed = parse_sale_description("PLAINTIFF'S UPSET BID IS $129,99.84 IN ACCORDANCE WITH")
    assert malformed.alternate_upset_price is None


def test_statute_numbers_are_not_money():
    from pipeline.parse_sale_description import parse_sale_description

    parsed = parse_sale_description(
        "THE ESTIMATED GOOD FAITH UPSET AMOUNT PURSUANT TO NJSA 2A:50-64(12)(5)(A) IS $264,831.71. (BASED UPON"
    )

    assert str(parsed.estimated_upset_price) == "264831.71"
    assert parsed.alternate_upset_price is None


def test_portal_amounts_read_the_listed_fields_not_the_notice():
    from pipeline.parse_sale_description import portal_amounts

    page = (
        "Description:\nTHE ESTIMATED GOOD FAITH UPSET AMOUNT ... IS $264,831.71.\n"
        "Approx. Upset*:\n$241,726.98\nAttorney:\nMARTONE & UHLMANN PC\n"
    )
    assert portal_amounts(page) == {"upset": Decimal("241726.98"), "judgment": None}

    monmouth = "Approx. Judgment*:\n$318,038.53\nAttorney:\nX\n"
    assert portal_amounts(monmouth) == {"upset": None, "judgment": Decimal("318038.53")}

    cumberland = "Approx. Judgment*:\n$202,962.74\nUpset Amount:\n$100.00\n"
    assert portal_amounts(cumberland) == {"upset": None, "judgment": Decimal("202962.74")}


def test_zero_portal_upset_means_not_published():
    from pipeline.parse_sale_description import portal_amounts

    assert portal_amounts("Approx. Upset*:\n$0.00\nAttorney:\nX\n")["upset"] is None
