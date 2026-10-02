from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.liens.models import LienRecord, LienStatus


@dataclass(frozen=True)
class PropertyIdentity:
    property_id: str
    address: str
    county: str
    municipality: str | None = None
    block: str | None = None
    lot: str | None = None
    qualifier: str | None = None
    pams_pin: str | None = None
    current_owners: tuple[str, ...] = ()
    historical_owners: tuple[str, ...] = ()


class LienSourceAdapter(ABC):
    name: str
    source_type: str

    @abstractmethod
    async def search_property(
        self,
        identity: PropertyIdentity,
    ) -> list[LienRecord]:
        raise NotImplementedError

    async def search_property_with_raw(self, identity: PropertyIdentity):
        """Return normalized records plus auditable source payloads when supported."""
        return await self.search_property(identity), [], []

    async def search_owner(self, owner: str, identity: PropertyIdentity | None = None) -> list[LienRecord]:
        """Optional owner search hook; sources may return an empty/manual result."""
        return []

    async def fetch_record_details(self, record: object) -> object:
        """Optional public detail-page hook. Adapters must not bypass access controls."""
        return record

    async def normalize_record(self, raw_record: object) -> LienRecord | None:
        """Optional single-record normalization hook."""
        return None


class MunicipalChargeSourceAdapter(ABC):
    """Public municipal tax/utility contract with an explicit manual fallback."""

    name: str
    source_type = "MUNICIPAL_TAX_AND_UTILITY"

    @abstractmethod
    async def search_property(self, identity: PropertyIdentity) -> list[LienRecord]:
        raise NotImplementedError

    def manual_review(self, identity: PropertyIdentity, source_url: str | None = None) -> dict[str, object]:
        return {
            "status": "MANUAL_REVIEW_REQUIRED",
            "source": self.name,
            "source_url": source_url,
            "municipality": identity.municipality,
            "property_address": identity.address,
            "block": identity.block,
            "lot": identity.lot,
            "pams_pin": identity.pams_pin,
            "recommended_search_terms": [identity.address, identity.block or "", identity.lot or "", *identity.current_owners],
        }


MONEY = r"\$\s*((?:\d{1,3}(?:,\s*\d{3})+|\d+)(?:\.\d{1,2})?)"


def _amount(value: str) -> Decimal | None:
    try:
        return Decimal(value.replace(",", "").replace(" ", ""))
    except (InvalidOperation, AttributeError):
        return None


def _first_amount(text: str, patterns: list[str]) -> Decimal | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            return _amount(match.group(1))
    return None


def _amount_after_label(
    text: str,
    label: str,
    *,
    max_distance: int,
    stop_labels: tuple[str, ...],
) -> Decimal | None:
    for match in re.finditer(label, text, re.IGNORECASE):
        window = text[match.end():match.end() + max_distance]
        money = re.search(MONEY, window)
        if not money:
            continue
        prefix = window[:money.start()].lower()
        if any(stop in prefix for stop in stop_labels):
            continue
        return _amount(money.group(1))
    return None


def parse_civilview_disclosures(
    description: str,
    *,
    source_url: str | None,
    plaintiff: str | None,
    defendant: str | None,
    case_number: str | None,
) -> list[LienRecord]:
    """Extract only explicitly disclosed obligations from a saved sale notice."""
    text = " ".join(description.replace("\xa0", " ").split())
    records: list[LienRecord] = []

    sewer = _amount_after_label(
        text,
        r"(?:water\s*(?:/|and|&)?\s*)?sewer",
        max_distance=260,
        stop_labels=("upset price", "judgment", "approx. judgment", "attorney:"),
    )
    if sewer is not None:
        records.append(LienRecord(
            lien_type="MUNICIPAL_LIEN",
            lien_subtype="SEWER_CHARGE",
            status=LienStatus.POSSIBLY_ACTIVE,
            current_amount=sewer,
            debtor_name=defendant,
            match_confidence=92,
            match_reason="Amount explicitly disclosed in the property-specific CivilView sale notice.",
            priority_classification="POTENTIALLY_SURVIVING",
            priority_confidence=45,
            survival_classification="MAY_SURVIVE",
            survival_confidence=45,
            requires_manual_review=True,
            source_name="CIVILVIEW_DISCLOSURE",
            source_url=source_url,
        ))

    advances = _amount_after_label(
        text,
        r"additional\s+advances|advances",
        max_distance=240,
        stop_labels=("judgment", "approx. judgment", "upset price", "attorney:"),
    )
    if advances is not None:
        records.append(LienRecord(
            lien_type="OTHER",
            lien_subtype="PLAINTIFF_ADVANCES",
            status=LienStatus.POSSIBLY_ACTIVE,
            current_amount=advances,
            creditor_name=plaintiff,
            debtor_name=defendant,
            case_number=case_number,
            is_foreclosing_lien=True,
            match_confidence=95,
            match_reason="Additional advances explicitly disclosed in the foreclosure sale notice.",
            priority_classification="FORECLOSING_CLAIM",
            priority_confidence=70,
            survival_classification="UNKNOWN",
            survival_confidence=30,
            requires_manual_review=True,
            source_name="CIVILVIEW_DISCLOSURE",
            source_url=source_url,
        ))

    if re.search(r"tax(?:es)?\s+current\s+through", text, re.IGNORECASE):
        records.append(LienRecord(
            lien_type="PROPERTY_TAX",
            lien_subtype="DISCLOSED_CURRENT_THROUGH_DATE",
            status=LienStatus.UNKNOWN,
            debtor_name=defendant,
            match_confidence=90,
            match_reason="CivilView notice states taxes were current only through a specified period.",
            priority_classification="SUPER_PRIORITY_POSSIBLE",
            priority_confidence=65,
            survival_classification="MAY_SURVIVE",
            survival_confidence=70,
            requires_manual_review=True,
            source_name="CIVILVIEW_DISCLOSURE",
            source_url=source_url,
        ))

    if re.search(
        r"water.{0,100}(?:unable\s+to\s+confirm|cannot\s+confirm|unknown)",
        text,
        re.IGNORECASE,
    ):
        records.append(LienRecord(
            lien_type="MUNICIPAL_LIEN",
            lien_subtype="WATER_CHARGE_UNKNOWN",
            status=LienStatus.UNKNOWN,
            debtor_name=defendant,
            match_confidence=90,
            match_reason="The sale notice explicitly says the water balance could not be confirmed.",
            priority_classification="UNKNOWN",
            survival_classification="UNKNOWN",
            requires_manual_review=True,
            source_name="CIVILVIEW_DISCLOSURE",
            source_url=source_url,
        ))

    return records
