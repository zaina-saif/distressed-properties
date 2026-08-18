"""Shared, explainable parcel-candidate scoring for every county adapter."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

SUFFIXES = {
    "AVENUE": "AVE", "BOULEVARD": "BLVD", "COURT": "CT", "DRIVE": "DR",
    "HIGHWAY": "HWY", "LANE": "LN", "PLACE": "PL", "ROAD": "RD",
    "STREET": "ST", "TERRACE": "TER", "TURNPIKE": "TPKE",
    "FIRST": "1", "1ST": "1", "SECOND": "2", "2ND": "2",
    "THIRD": "3", "3RD": "3", "FOURTH": "4", "4TH": "4",
    "FIFTH": "5", "5TH": "5", "SIXTH": "6", "6TH": "6",
    "SEVENTH": "7", "7TH": "7", "EIGHTH": "8", "8TH": "8",
    "NINTH": "9", "9TH": "9", "TENTH": "10", "10TH": "10",
}


def normalize_text(value: str | None) -> str:
    tokens = re.findall(r"[A-Z0-9]+", (value or "").upper())
    return "".join(SUFFIXES.get(token, token) for token in tokens)


def normalize_component(value: str | None) -> str:
    compact = re.sub(r"[^A-Z0-9-]", "", (value or "").upper())
    return compact.lstrip("0") or ("0" if compact else "")


def pams_pin(municipality_code: str, block: str, lot: str, qualifier: str = "") -> str:
    components = [municipality_code.strip(), normalize_component(block), normalize_component(lot)]
    normalized_qualifier = normalize_component(qualifier)
    if normalized_qualifier:
        components.append(normalized_qualifier)
    return "_".join(components)


def address_corrobates(subject: str | None, candidate: str | None) -> bool:
    subject_key=normalize_text(subject); candidate_key=normalize_text(candidate)
    if not subject_key or not candidate_key:
        return False
    if candidate_key in subject_key:
        return True
    subject_token_text=re.sub(r"(?<=[A-Z])(?=\d)"," ",(subject or "").upper())
    candidate_token_text=re.sub(r"(?<=[A-Z])(?=\d)"," ",(candidate or "").upper())
    subject_tokens=set(re.findall(r"[A-Z0-9]+",subject_token_text))
    candidate_tokens=set(re.findall(r"[A-Z0-9]+",candidate_token_text))
    candidate_numbers={token for token in candidate_tokens if token.isdigit() and len(token)<=4}
    subject_numbers={token for token in subject_tokens if token.isdigit() and len(token)<=4}
    candidate_words={normalize_text(token) for token in candidate_tokens if not token.isdigit()}
    subject_words={normalize_text(token) for token in subject_tokens if not token.isdigit()}
    return bool(candidate_numbers and candidate_numbers<=subject_numbers
                and candidate_words and len(candidate_words&subject_words)/len(candidate_words)>=.6)


@dataclass(frozen=True)
class IdentitySubject:
    municipality_code: str | None = None
    block: str | None = None
    lot: str | None = None
    qualifier: str | None = None
    address: str | None = None
    zip_code: str | None = None
    latitude: float | None = None
    longitude: float | None = None


@dataclass(frozen=True)
class ParcelCandidate:
    municipality_code: str
    block: str
    lot: str
    qualifier: str = ""
    address: str | None = None
    zip_code: str | None = None


@dataclass
class MatchScore:
    total: float
    components: dict[str, float] = field(default_factory=dict)
    conflicts: list[str] = field(default_factory=list)

    @property
    def decision(self) -> str:
        if self.conflicts:
            return "REVIEW"
        if self.total >= 95:
            return "AUTO_ACCEPT"
        if self.total >= 80:
            return "REVIEW"
        return "UNRESOLVED"


def score_candidate(subject: IdentitySubject, candidate: ParcelCandidate) -> MatchScore:
    components: dict[str, float] = {}
    conflicts: list[str] = []

    if subject.municipality_code:
        if subject.municipality_code.strip() == candidate.municipality_code.strip():
            components["municipality_exact"] = 25
        else:
            components["municipality_conflict"] = -50
            conflicts.append("municipality_conflict")

    for name, weight in (("block", 25), ("lot", 25), ("qualifier", 15)):
        expected = normalize_component(getattr(subject, name))
        actual = normalize_component(getattr(candidate, name))
        if not expected:
            continue
        if expected == actual:
            components[f"{name}_exact"] = weight
        else:
            components[f"{name}_conflict"] = -40 if name != "qualifier" else -20
            conflicts.append(f"{name}_conflict")

    subject_address = normalize_text(subject.address)
    candidate_address = normalize_text(candidate.address)
    if subject_address and candidate_address:
        ratio = SequenceMatcher(None, subject_address, candidate_address).ratio()
        components["address_similarity"] = round(20 * ratio, 2)
        subject_number = re.match(r"\d+[A-Z]?", subject_address)
        candidate_number = re.match(r"\d+[A-Z]?", candidate_address)
        if subject_number and candidate_number and subject_number.group() != candidate_number.group():
            components["house_number_conflict"] = -40
            conflicts.append("house_number_conflict")

    if subject.zip_code and candidate.zip_code:
        if subject.zip_code[:5] == candidate.zip_code[:5]:
            components["zip_exact"] = 5
        else:
            components["zip_conflict"] = -10
            conflicts.append("zip_conflict")

    return MatchScore(round(sum(components.values()), 2), components, conflicts)
