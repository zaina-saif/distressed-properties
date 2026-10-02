"""Canonical property identity assembly for lien source routing."""

from __future__ import annotations

import re
from typing import Any

from app.liens.matching import normalize_address, normalize_name
from app.liens.sources import PropertyIdentity


def _owners(defendant: str | None) -> tuple[str, ...]:
    return tuple(
        value.strip()
        for value in re.split(r",|;|\band\b", defendant or "", flags=re.IGNORECASE)
        if value.strip() and value.strip().lower() not in {"et al", "et al."}
    )


def property_identity_from_sale(sale: dict[str, Any]) -> PropertyIdentity:
    """Build the strongest available identity without inventing parcel data."""
    address = sale.get("normalized_address") or sale.get("property_address") or ""
    owners = _owners(sale.get("defendant"))
    return PropertyIdentity(
        property_id=str(sale["property_id"]),
        address=normalize_address(address),
        county=sale.get("county") or "",
        municipality=sale.get("municipality") or sale.get("city"),
        block=sale.get("block"),
        lot=sale.get("lot"),
        qualifier=sale.get("qualifier"),
        pams_pin=sale.get("pams_pin"),
        current_owners=tuple(normalize_name(owner) for owner in owners),
    )
