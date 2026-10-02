"""Conservative property/owner matching for public-record lien documents."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.liens.sources import PropertyIdentity


def normalize_name(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9 ]+", "", (value or "").upper()).strip()


def normalize_address(value: str | None) -> str:
    value = re.sub(r"[^A-Z0-9 ]+", " ", (value or "").upper())
    replacements = {
        " STREET ": " ST ", " ROAD ": " RD ", " AVENUE ": " AVE ",
        " DRIVE ": " DR ", " LANE ": " LN ", " COURT ": " CT ",
        " HIGHWAY ": " HWY ", " BOULEVARD ": " BLVD ",
    }
    value = f" {value} "
    for source, target in replacements.items():
        value = value.replace(source, target)
    return " ".join(value.split())


@dataclass(frozen=True)
class MatchResult:
    confidence: int
    method: str
    reason: str
    requires_manual_review: bool


def match_public_record(identity: PropertyIdentity, record: dict[str, object]) -> MatchResult:
    confidence = 0
    methods: list[str] = []
    reasons: list[str] = []
    if identity.pams_pin and record.get("pams_pin") and str(identity.pams_pin) == str(record["pams_pin"]):
        confidence += 100
        methods.append("PAMS_PIN_EXACT")
        reasons.append("Exact PAMS PIN match")
    block = str(record.get("block") or "")
    lot = str(record.get("lot") or "")
    if identity.block and identity.lot and block == str(identity.block) and lot == str(identity.lot):
        confidence = max(confidence, 90)
        methods.append("BLOCK_LOT_EXACT")
        reasons.append("Exact block and lot match")
    if normalize_address(identity.address) and normalize_address(identity.address) == normalize_address(str(record.get("property_address") or "")):
        confidence = max(confidence, 85)
        methods.append("ADDRESS_EXACT")
        reasons.append("Exact normalized property address match")
    owners = {normalize_name(name) for name in (*identity.current_owners, *identity.historical_owners) if name}
    record_owner = normalize_name(str(record.get("debtor_name") or ""))
    if record_owner and record_owner in owners:
        confidence = max(confidence, 80 if confidence else 45)
        methods.append("OWNER_EXACT")
        reasons.append("Exact owner/debtor name match")
    if identity.municipality and str(record.get("municipality") or "").upper() == identity.municipality.upper():
        confidence += 5 if confidence else 10
        methods.append("MUNICIPALITY_MATCH")
        reasons.append("Municipality matches")
    confidence = min(confidence, 100)
    if not reasons:
        reasons.append("No reliable parcel, address, or owner evidence was returned")
    return MatchResult(
        confidence=confidence,
        method="+".join(methods) or "NO_SECONDARY_MATCH",
        reason="; ".join(reasons),
        requires_manual_review=confidence < 85,
    )
