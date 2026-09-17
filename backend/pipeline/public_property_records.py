"""Canonical records and conservative coercion for public AVM source adapters."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any


def text_value(value: Any) -> str | None:
    value = str(value).strip() if value is not None else ""
    return value or None


def decimal_value(value: Any) -> Decimal | None:
    value = text_value(value)
    if value is None:
        return None
    try:
        number = Decimal(value.replace(",", "").replace("$", ""))
        return number if number.is_finite() else None
    except InvalidOperation:
        return None


def integer_value(value: Any) -> int | None:
    number = decimal_value(value)
    return int(number) if number is not None else None


def date_value(value: Any) -> date | None:
    value = text_value(value)
    if value is None:
        return None
    for candidate in (value, value.replace(".", "-"), value.replace("/", "-")):
        try:
            return date.fromisoformat(candidate[:10])
        except ValueError:
            continue
    return None


def stable_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()


@dataclass(frozen=True)
class PropertySnapshot:
    source_id: str
    state: str
    county: str
    source_parcel_id: str
    snapshot_year: int
    street_address: str | None = None
    city: str | None = None
    zip_code: str | None = None
    longitude: Decimal | None = None
    latitude: Decimal | None = None
    property_type: str | None = None
    land_use_code: str | None = None
    year_built: int | None = None
    living_area: int | None = None
    land_area: Decimal | None = None
    land_area_unit: str | None = None
    bedrooms: Decimal | None = None
    bathrooms: Decimal | None = None
    land_value: Decimal | None = None
    improvement_value: Decimal | None = None
    total_assessed_value: Decimal | None = None
    source_updated_at: datetime | None = None
    house_number_unavailable: bool = False
    source_hash: str = ""

    def params(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PropertySale:
    source_id: str
    state: str
    county: str
    source_parcel_id: str
    transaction_id: str
    sale_date: date
    sale_price: Decimal
    recording_date: date | None = None
    conveyance_code: str | None = None
    arms_length: bool | None = None
    source_hash: str = ""

    def params(self) -> dict[str, Any]:
        return asdict(self)


def source_timestamp(value: Any) -> datetime | None:
    value = text_value(value)
    if not value:
        return None
    if len(value) == 8 and value.isdigit():
        try:
            return datetime.strptime(value, "%Y%m%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None
