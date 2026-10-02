"""Deterministic bidder-facing lien/title summary generation."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.liens.models import LienRecord, LienRiskReport, SourceCoverage, SourceStatus


def _status(value: object) -> str:
    return getattr(value, "value", str(value))


def _coverage_item(item: SourceCoverage) -> dict[str, Any]:
    return {
        "source_name": item.source_name,
        "source_type": item.source_type,
        "status": _status(item.status),
        "checked_at": item.checked_at.isoformat() if item.checked_at else None,
        "source_url": item.source_url,
        "records_found": item.records_found,
        "message": item.message,
    }


def build_preliminary_summary(
    report: LienRiskReport,
    coverage: list[SourceCoverage],
    liens: list[LienRecord],
    *,
    county: str | None = None,
    municipality: str | None = None,
    identity: dict[str, Any] | None = None,
    enrichment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build only evidence-backed interpretation; missing coverage stays visible."""
    findings: list[dict[str, Any]] = []
    open_liens = [item for item in liens if item.status.value in {"ACTIVE", "POSSIBLY_ACTIVE", "UNKNOWN"}]
    for item in open_liens:
        label = item.lien_type.replace("_", " ").title()
        severity = "HIGH" if item.lien_type in {"TAX_SALE_CERTIFICATE", "FEDERAL_TAX_LIEN", "STATE_TAX_LIEN"} else "MEDIUM"
        findings.append({
            "finding_id": f"lien:{item.id or item.instrument_number or label}",
            "type": item.lien_type,
            "severity": severity,
            "label": f"{label} requires review",
            "message": item.match_reason,
            "evidence_ids": [item.id or item.instrument_number],
            "confidence": item.match_confidence,
        })
    if any(item.lien_type == "MORTGAGE" and item.status.value in {"ACTIVE", "POSSIBLY_ACTIVE", "UNKNOWN"} for item in liens):
        findings.append({
            "finding_id": "mortgage:unresolved",
            "type": "MORTGAGE_STATUS",
            "severity": "HIGH",
            "label": "Mortgage record has no confirmed discharge in checked records",
            "message": "No matching discharge is evidence of incomplete coverage, not proof that the mortgage remains active.",
            "evidence_ids": [item.id for item in liens if item.lien_type == "MORTGAGE"],
            "confidence": 60,
        })
    if enrichment:
        violations = enrichment.get("municipal_violations_count")
        if violations:
            findings.append({
                "finding_id": "municipal:violations",
                "type": "MUNICIPAL_CHARGE",
                "severity": "MEDIUM",
                "label": f"{violations} municipal complaint/violation records retrieved",
                "message": "These records are public complaints or violations and do not establish a lien or balance.",
                "evidence_ids": ["enrichment:socrata"],
                "confidence": 80,
            })
        if enrichment.get("tax_delinquency_status") in {"Delinquent", "Unknown"}:
            findings.append({
                "finding_id": "tax:coverage",
                "type": "PROPERTY_TAX",
                "severity": "INFO" if enrichment.get("tax_delinquency_status") == "Unknown" else "HIGH",
                "label": "Property-tax status requires verification" if enrichment.get("tax_delinquency_status") == "Unknown" else "Delinquent tax indicator retrieved",
                "message": "No returned balance is not evidence that no tax lien exists.",
                "evidence_ids": ["enrichment:arcgis"],
                "confidence": 40 if enrichment.get("tax_delinquency_status") == "Unknown" else 75,
            })
    for item in coverage:
        if item.status not in {SourceStatus.SUCCESS, SourceStatus.PARTIAL}:
            findings.append({
                "finding_id": f"coverage:{item.source_type}",
                "type": "SOURCE_COVERAGE",
                "severity": "INFO",
                "label": f"{item.source_name} requires {str(item.status).replace('_', ' ').lower()}",
                "message": item.message or "The source was not successfully checked.",
                "evidence_ids": [],
                "confidence": 100,
            })

    checked = sum(item.status in {SourceStatus.SUCCESS, SourceStatus.PARTIAL} for item in coverage)
    unavailable = sum(item.status in {SourceStatus.FAILED, SourceStatus.NOT_CONFIGURED} for item in coverage)
    manual = sum(item.status == SourceStatus.MANUAL_REVIEW_REQUIRED for item in coverage)
    manual_items = [
        {
            "source": item.source_name,
            "reason": item.message or str(item.status).replace("_", " "),
            "source_url": item.source_url,
            **(identity or {}),
        }
        for item in coverage
        if item.status not in {SourceStatus.SUCCESS, SourceStatus.PARTIAL}
    ]
    evidence_findings = [item for item in findings if item["type"] != "SOURCE_COVERAGE"]
    if not evidence_findings:
        headline = "Insufficient public-record coverage"
        summary_text = "Insufficient public-record coverage is currently available to assess this property's lien position. Manual or professional title review is recommended."
    else:
        headline = evidence_findings[0]["label"]
        statements = [item["label"] + "." for item in findings if item["type"] != "SOURCE_COVERAGE"]
        if unavailable or manual:
            statements.append("Additional obligations may exist because some sources were unavailable or require manual review.")
        summary_text = " ".join(statements)
    return {
        "risk_level": report.risk_level,
        "confidence": report.confidence_score,
        "headline": headline,
        "summary_text": summary_text,
        "key_findings": findings,
        "coverage_summary": {
            "checked_sources": checked,
            "unavailable_sources": unavailable,
            "manual_review_sources": manual,
            "total_sources": len(coverage),
        },
        "coverage": [_coverage_item(item) for item in coverage],
        "manual_review": manual_items,
        "data_freshness": enrichment.get("data_freshness_status") if enrichment else "UNKNOWN",
        "calculated_at": report.calculated_at.isoformat() if isinstance(report.calculated_at, datetime) else report.calculated_at,
        "disclaimer": report.disclaimer,
    }
