from datetime import datetime, timezone
from decimal import Decimal

from app.liens.models import LienRecord, LienRiskReport, LienStatus, SourceCoverage, SourceStatus
from app.liens.summary import build_preliminary_summary
from app.liens.source_registry import county_capabilities, municipal_capabilities


def report(liens, coverage):
    return LienRiskReport(
        property_id="property-1", risk_score=58, risk_level="HIGH", confidence_score=42,
        known_exposure=Decimal("0"), components={}, flags=[], source_coverage=coverage,
        liens=liens, calculated_at=datetime.now(timezone.utc),
    )


def test_summary_keeps_missing_sources_as_manual_review():
    coverage = [SourceCoverage(source_name="Municipal tax", source_type="MUNICIPAL", status=SourceStatus.MANUAL_REVIEW_REQUIRED, message="Collector confirmation required")]
    summary = build_preliminary_summary(report([], coverage), coverage, [], identity={"property_address": "1 MAIN ST"})
    assert summary["headline"] == "Insufficient public-record coverage"
    assert summary["coverage_summary"]["manual_review_sources"] == 1
    assert "not confirm" not in summary["summary_text"].lower()
    assert summary["manual_review"][0]["source"] == "Municipal tax"


def test_summary_links_active_mortgage_to_evidence():
    lien = LienRecord(
        id="lien-1", lien_type="MORTGAGE", status=LienStatus.POSSIBLY_ACTIVE,
        creditor_name="Example Bank", debtor_name="Jane Doe", original_amount=Decimal("250000"),
        match_confidence=92, match_reason="Exact block and lot match", source_name="MONMOUTH_COUNTY_OPRS",
    )
    coverage = [SourceCoverage(source_name="Monmouth OPRS", source_type="COUNTY_LAND_RECORDS", status=SourceStatus.SUCCESS)]
    summary = build_preliminary_summary(report([lien], coverage), coverage, [lien])
    finding = next(item for item in summary["key_findings"] if item["type"] == "MORTGAGE")
    assert finding["evidence_ids"] == ["lien-1"]
    assert "Mortgage" in finding["label"]


def test_source_registry_routes_monmouth_and_keeps_municipal_manual():
    county = county_capabilities("Monmouth")
    assert county[0].access_status == "SUPPORTED"
    assert county[0].source_type == "COUNTY_LAND_RECORDS"
    municipal = municipal_capabilities("Glen Ridge", "Essex")
    assert municipal[0].access_status == "MANUAL_ONLY"
