from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class LienStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SATISFIED = "SATISFIED"
    DISCHARGED = "DISCHARGED"
    RELEASED = "RELEASED"
    REDEEMED = "REDEEMED"
    EXPIRED = "EXPIRED"
    POSSIBLY_ACTIVE = "POSSIBLY_ACTIVE"
    UNKNOWN = "UNKNOWN"


class SourceStatus(StrEnum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
    NOT_CONFIGURED = "NOT_CONFIGURED"


class LienRecord(BaseModel):
    id: str | None = None
    lien_type: str
    lien_subtype: str | None = None
    status: LienStatus = LienStatus.UNKNOWN
    creditor_name: str | None = None
    debtor_name: str | None = None
    original_amount: Decimal | None = None
    current_amount: Decimal | None = None
    recording_date: date | None = None
    effective_date: date | None = None
    instrument_number: str | None = None
    docket_number: str | None = None
    case_number: str | None = None
    is_foreclosing_lien: bool = False
    match_confidence: int = Field(ge=0, le=100)
    match_reason: str
    priority_classification: str = "UNKNOWN"
    priority_confidence: int = Field(default=0, ge=0, le=100)
    survival_classification: str = "UNKNOWN"
    survival_confidence: int = Field(default=0, ge=0, le=100)
    requires_manual_review: bool = True
    source_name: str
    source_url: str | None = None
    source_effective_at: datetime | None = None


class SourceCoverage(BaseModel):
    source_name: str
    source_type: str
    status: SourceStatus
    checked_at: datetime | None = None
    source_url: str | None = None
    records_found: int = 0
    message: str | None = None


class RiskFlag(BaseModel):
    severity: str
    category: str
    message: str
    confidence: int = Field(ge=0, le=100)
    related_lien_id: str | None = None


class LienRiskReport(BaseModel):
    property_id: str
    risk_score: int = Field(ge=0, le=100)
    risk_level: str
    confidence_score: int = Field(ge=0, le=100)
    known_exposure: Decimal
    components: dict[str, int]
    flags: list[RiskFlag]
    source_coverage: list[SourceCoverage]
    liens: list[LienRecord]
    calculated_at: datetime
    calculation_version: str = "lien-screen-v1"
    disclaimer: str = (
        "Preliminary public-record screening only. This is not a certified "
        "title search, title insurance, or legal advice. Verify all interests "
        "and amounts with qualified professionals before bidding."
    )


class RawSourceRecord(BaseModel):
    source_name: str
    source_record_id: str | None = None
    source_url: str | None = None
    payload: dict[str, Any]
    retrieved_at: datetime
