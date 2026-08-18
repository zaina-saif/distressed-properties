from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.liens.models import (
    LienRecord,
    LienRiskReport,
    LienStatus,
    RiskFlag,
    SourceCoverage,
    SourceStatus,
)


RISK_WEIGHTS = {
    "TAX_SALE_CERTIFICATE": 32,
    "PROPERTY_TAX": 25,
    "MUNICIPAL_LIEN": 24,
    "FEDERAL_TAX_LIEN": 28,
    "STATE_TAX_LIEN": 24,
    "HOMEOWNER_ASSOCIATION_LIEN": 18,
    "MORTGAGE": 15,
    "JUDGMENT": 13,
    "CONSTRUCTION_LIEN": 16,
    "UCC": 10,
    "LIS_PENDENS": 8,
    "OTHER": 8,
}

OPEN_STATUSES = {
    LienStatus.ACTIVE,
    LienStatus.POSSIBLY_ACTIVE,
    LienStatus.UNKNOWN,
}


def _level(score: int) -> str:
    if score >= 75:
        return "VERY_HIGH"
    if score >= 50:
        return "HIGH"
    if score >= 25:
        return "MODERATE"
    return "LOW"


def calculate_lien_risk(
    property_id: str,
    liens: list[LienRecord],
    coverage: list[SourceCoverage],
) -> LienRiskReport:
    """Calculate screening risk without treating missing data as clean title."""
    open_liens = [item for item in liens if item.status in OPEN_STATUSES]
    surviving = [
        item for item in open_liens
        if item.survival_classification in {"LIKELY_SURVIVES", "MAY_SURVIVE"}
    ]
    manual = [item for item in liens if item.requires_manual_review]

    title_complexity = min(100, len(open_liens) * 14 + len(liens) * 3)
    surviving_risk = min(
        100,
        sum(
            round(
                RISK_WEIGHTS.get(item.lien_type, RISK_WEIGHTS["OTHER"])
                * max(item.match_confidence, 25) / 100
            )
            for item in surviving
        ),
    )
    tax_municipal = min(
        100,
        sum(
            RISK_WEIGHTS.get(item.lien_type, 0)
            for item in open_liens
            if item.lien_type in {
                "TAX_SALE_CERTIFICATE", "PROPERTY_TAX", "MUNICIPAL_LIEN",
                "FEDERAL_TAX_LIEN", "STATE_TAX_LIEN",
            }
        ),
    )
    judgment = min(
        100,
        sum(20 for item in open_liens if item.lien_type == "JUDGMENT"),
    )
    mortgage = min(
        100,
        sum(
            18 if not item.is_foreclosing_lien else 5
            for item in open_liens if item.lien_type == "MORTGAGE"
        ),
    )

    successful = sum(item.status == SourceStatus.SUCCESS for item in coverage)
    partial = sum(item.status == SourceStatus.PARTIAL for item in coverage)
    unavailable = len(coverage) - successful - partial
    completeness = round(
        (successful + partial * 0.5) / len(coverage) * 100
    ) if coverage else 0
    data_quality_risk = 100 - completeness
    manual_review_risk = min(100, len(manual) * 12 + unavailable * 10)

    components = {
        "surviving_lien_risk": surviving_risk,
        "title_complexity_risk": title_complexity,
        "tax_municipal_risk": tax_municipal,
        "judgment_risk": judgment,
        "mortgage_priority_risk": mortgage,
        "data_quality_risk": data_quality_risk,
        "manual_review_risk": manual_review_risk,
    }
    score = round(
        surviving_risk * 0.25
        + tax_municipal * 0.18
        + mortgage * 0.12
        + judgment * 0.10
        + title_complexity * 0.10
        + data_quality_risk * 0.15
        + manual_review_risk * 0.10
    )
    score = min(100, max(0, score))

    flags: list[RiskFlag] = []
    for item in surviving:
        flags.append(RiskFlag(
            severity="HIGH" if item.survival_classification == "LIKELY_SURVIVES" else "MEDIUM",
            category=item.lien_type,
            message=(
                f"{item.lien_type.replace('_', ' ').title()} may survive the sale; "
                "professional priority review is required."
            ),
            confidence=min(item.match_confidence, item.survival_confidence),
            related_lien_id=item.id,
        ))
    for item in coverage:
        if item.status not in {SourceStatus.SUCCESS, SourceStatus.PARTIAL}:
            flags.append(RiskFlag(
                severity="MEDIUM",
                category="DATA_COVERAGE",
                message=f"{item.source_name} was not checked automatically: {item.message or item.status}.",
                confidence=100,
            ))
    if not liens:
        flags.append(RiskFlag(
            severity="MEDIUM",
            category="DATA_COVERAGE",
            message="No lien records were found. This does not confirm clean title.",
            confidence=100,
        ))

    known_exposure = sum(
        (item.current_amount or item.original_amount or Decimal("0"))
        for item in surviving
        if item.status in {LienStatus.ACTIVE, LienStatus.POSSIBLY_ACTIVE}
    )
    confidence = min(100, round(completeness * 0.7 + (
        sum(item.match_confidence for item in liens) / len(liens) if liens else 0
    ) * 0.3))

    return LienRiskReport(
        property_id=property_id,
        risk_score=score,
        risk_level=_level(score),
        confidence_score=confidence,
        known_exposure=known_exposure,
        components=components,
        flags=flags,
        source_coverage=coverage,
        liens=liens,
        calculated_at=datetime.now(timezone.utc),
    )
