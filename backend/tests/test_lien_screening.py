from decimal import Decimal

from app.liens.models import (
    LienRecord,
    LienStatus,
    SourceCoverage,
    SourceStatus,
)
from app.liens.risk import calculate_lien_risk
from app.liens.sources import parse_civilview_disclosures


NOTICE = """
Taxes current through 2nd Quarter of 2026. Water-Plaintiff is unable to
confirm these amounts. Prospective purchasers must conduct their own
investigation. Sewer open balance in amount $234.28, good through September
1, 2026. Subject to Additional advances for taxes, insurance and inspections
in the amount of $11,593.57. Approximate Judgment $232,054.98.
"""


def test_civilview_parser_extracts_only_disclosed_risk_records():
    records = parse_civilview_disclosures(
        NOTICE,
        source_url="https://example.test/sale/1",
        plaintiff="BANK",
        defendant="OWNER",
        case_number="F-123",
    )

    by_subtype = {record.lien_subtype: record for record in records}

    assert by_subtype["SEWER_CHARGE"].current_amount == Decimal("234.28")
    assert by_subtype["PLAINTIFF_ADVANCES"].current_amount == Decimal("11593.57")
    assert by_subtype["DISCLOSED_CURRENT_THROUGH_DATE"].status == LienStatus.UNKNOWN
    assert by_subtype["WATER_CHARGE_UNKNOWN"].requires_manual_review is True
    assert all(record.match_reason for record in records)


def test_sewer_parser_does_not_treat_account_or_date_as_money():
    records = parse_civilview_disclosures(
        "Sewer: Utility 1 Main St Acct: 4166751 0 07/01/2026 - 09/30/2026 $100.00 OPEN",
        source_url=None,
        plaintiff=None,
        defendant=None,
        case_number=None,
    )

    sewer = next(item for item in records if item.lien_subtype == "SEWER_CHARGE")
    assert sewer.current_amount == Decimal("100.00")


def test_sewer_and_advances_do_not_capture_later_upset_or_judgment():
    records = parse_civilview_disclosures(
        "Sewer current through August 1, 2026. Upset Price: $146,540.44. "
        "Advances for taxes, if any. Approx. Judgment: $10,840,376.04",
        source_url=None,
        plaintiff=None,
        defendant=None,
        case_number=None,
    )

    assert not any(item.lien_subtype == "SEWER_CHARGE" for item in records)
    assert not any(item.lien_subtype == "PLAINTIFF_ADVANCES" for item in records)


def test_risk_engine_penalizes_missing_source_coverage():
    lien = LienRecord(
        lien_type="MUNICIPAL_LIEN",
        lien_subtype="SEWER_CHARGE",
        status=LienStatus.POSSIBLY_ACTIVE,
        current_amount=Decimal("234.28"),
        match_confidence=92,
        match_reason="Property-specific notice",
        priority_classification="POTENTIALLY_SURVIVING",
        priority_confidence=45,
        survival_classification="MAY_SURVIVE",
        survival_confidence=45,
        requires_manual_review=True,
        source_name="CIVILVIEW_DISCLOSURE",
    )
    coverage = [
        SourceCoverage(
            source_name="CivilView",
            source_type="SHERIFF_NOTICE",
            status=SourceStatus.SUCCESS,
        ),
        SourceCoverage(
            source_name="County records",
            source_type="COUNTY_LAND_RECORDS",
            status=SourceStatus.MANUAL_REVIEW_REQUIRED,
        ),
    ]

    report = calculate_lien_risk("property-1", [lien], coverage)

    assert report.known_exposure == Decimal("234.28")
    assert report.components["data_quality_risk"] == 50
    assert report.confidence_score < 100
    assert any(flag.category == "DATA_COVERAGE" for flag in report.flags)


def test_no_records_does_not_mean_low_confidence_clean_title():
    coverage = [
        SourceCoverage(
            source_name="County records",
            source_type="COUNTY_LAND_RECORDS",
            status=SourceStatus.NOT_CONFIGURED,
        )
    ]

    report = calculate_lien_risk("property-1", [], coverage)

    assert report.risk_score > 0
    assert report.confidence_score == 0
    assert any("does not confirm clean title" in flag.message for flag in report.flags)
