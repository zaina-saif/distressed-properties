"""Monmouth County OPRS public land-record adapter.

OPRS is an ASP.NET public search form. This adapter submits the documented
block/lot or owner search and parses only the returned public index rows. It
does not access images, authenticate, solve challenges, or bypass controls.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from bs4 import BeautifulSoup

from app.liens.matching import match_public_record, normalize_name
from app.liens.models import LienRecord, LienStatus
from app.liens.sources import LienSourceAdapter, PropertyIdentity


MONMOUTH_OPRS_URL = "https://oprs.co.monmouth.nj.us/Oprs/clerk/ClerkHome.aspx?op=basic"
SOURCE_NAME = "MONMOUTH_COUNTY_OPRS"
PARSER_VERSION = "monmouth-oprs-v1"
DOCUMENT_TYPE_FIELDS = {
    "MORTGAGE": ("MORTGAGE", "MORTGAGES"),
    "MORTGAGE_DISCHARGE": ("DISCHARGE", "CANCELLATION", "SATISFACTION", "RELEASE OF MORTGAGE"),
    "LIS_PENDENS": ("LIS PENDENS",),
    "FEDERAL_TAX_LIEN": ("FEDERAL LIEN", "IRS LIEN", "FED TAX LIEN"),
    "MUNICIPAL_LIEN": ("MUNICIPAL LIEN",),
    "CONSTRUCTION_LIEN": ("CONSTRUCTION LIEN", "BUILDING CONTRACT"),
    "TAX_SALE_CERTIFICATE": ("TAX SALE",),
}


class MonmouthSourceError(RuntimeError):
    """A public source failure that should be surfaced as manual review."""


@dataclass(frozen=True)
class MonmouthRawRecord:
    source_record_id: str
    source_url: str
    raw_data: dict[str, Any]
    content_hash: str
    retrieved_at: datetime


@dataclass(frozen=True)
class MonmouthSearchResult:
    liens: list[LienRecord]
    raw_records: list[MonmouthRawRecord]
    relationships: list[dict[str, Any]]
    source_status: str
    source_message: str | None = None


def _money(value: str | None) -> Decimal | None:
    if not value:
        return None
    match = re.search(r"\$?\s*([\d,]+(?:\.\d{1,2})?)", value)
    if not match:
        return None
    try:
        return Decimal(match.group(1).replace(",", ""))
    except InvalidOperation:
        return None


def _date(value: str | None) -> date | None:
    if not value:
        return None
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            pass
    return None


def _document_type(label: str) -> tuple[str, str | None]:
    upper = label.upper()
    if any(term in upper for term in DOCUMENT_TYPE_FIELDS["MORTGAGE_DISCHARGE"]):
        return "MORTGAGE_DISCHARGE", label
    for lien_type, terms in DOCUMENT_TYPE_FIELDS.items():
        if lien_type == "MORTGAGE_DISCHARGE":
            continue
        if any(term in upper for term in terms):
            return lien_type, label
    if "ASSIGNMENT" in upper:
        return "OTHER", "ASSIGNMENT"
    if "DEED" in upper:
        return "OTHER", "DEED"
    return "OTHER", label or None


def parse_oprs_results(html: str, source_url: str, identity: PropertyIdentity) -> tuple[list[MonmouthRawRecord], list[LienRecord], list[tuple[str, str, str, int]]]:
    soup = BeautifulSoup(html, "html.parser")
    retrieved_at = datetime.now(timezone.utc)
    raw_records: list[MonmouthRawRecord] = []
    liens: list[LienRecord] = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        headers = [cell.get_text(" ", strip=True) for cell in rows[0].find_all(["th", "td"])]
        if not headers or not any("instrument" in h.lower() or "document type" in h.lower() for h in headers):
            continue
        for row in rows[1:]:
            cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"])]
            if not cells:
                continue
            values = {headers[i]: cells[i] for i in range(min(len(headers), len(cells)))}
            combined = " ".join(cells)
            if not combined or "no records" in combined.lower():
                continue
            raw_id = next((v for k, v in values.items() if any(x in k.lower() for x in ("instrument", "document number")) and v), None)
            raw_id = raw_id or hashlib.sha256(combined.encode()).hexdigest()[:24]
            payload = {"columns": values, "row_text": combined}
            digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
            if any(existing.content_hash == digest or existing.source_record_id == raw_id for existing in raw_records):
                continue
            raw_records.append(MonmouthRawRecord(raw_id, source_url, payload, digest, retrieved_at))
            label = next((v for k, v in values.items() if "type" in k.lower() or "document" in k.lower()), "")
            if not label or label.lower() in {"county clerk", "search results", "results"}:
                raw_records.pop()
                continue
            lien_type, subtype = _document_type(label)
            amount = next((_money(v) for k, v in values.items() if any(x in k.lower() for x in ("amount", "consideration", "principal")) and _money(v) is not None), None)
            recording = next((_date(v) for k, v in values.items() if any(x in k.lower() for x in ("date", "recorded")) and _date(v)), None)
            debtor = next((v for k, v in values.items() if any(x in k.lower() for x in ("grantor", "mortgagor", "debtor")) and v), None)
            creditor = next((v for k, v in values.items() if any(x in k.lower() for x in ("grantee", "mortgagee", "creditor")) and v), None)
            source_address = next((v for k, v in values.items() if "address" in k.lower() and v), None)
            record = {
                "pams_pin": identity.pams_pin, "block": identity.block, "lot": identity.lot,
                "municipality": identity.municipality, "property_address": source_address,
                "debtor_name": debtor or next(iter(identity.current_owners), None),
            }
            match = match_public_record(identity, record)
            status = LienStatus.UNKNOWN
            if lien_type == "MORTGAGE":
                status = LienStatus.POSSIBLY_ACTIVE
            elif lien_type == "MORTGAGE_DISCHARGE" or any(term in label.upper() for term in ("RELEASE", "CANCELLATION", "SATISFACTION", "DISCHARGE")):
                status = LienStatus.DISCHARGED
            liens.append(LienRecord(
                lien_type=lien_type, lien_subtype=subtype, status=status,
                creditor_name=creditor, debtor_name=debtor,
                original_amount=amount, current_amount=amount,
                recording_date=recording, instrument_number=raw_id,
                match_confidence=match.confidence, match_reason=match.reason,
                priority_classification="UNKNOWN", priority_confidence=0,
                survival_classification="UNKNOWN", survival_confidence=0,
                requires_manual_review=True,
                source_name=SOURCE_NAME, source_url=source_url,
                source_effective_at=retrieved_at,
            ))
    relationships: list[tuple[str, str, str, int]] = []
    for mortgage in liens:
        if mortgage.lien_type != "MORTGAGE":
            continue
        for discharge in liens:
            if discharge.lien_type != "MORTGAGE_DISCHARGE":
                continue
            discharge_text = next((raw.raw_data.get("row_text", "") for raw in raw_records if raw.source_record_id == discharge.instrument_number), "")
            if mortgage.instrument_number and mortgage.instrument_number in discharge_text:
                relationships.append((mortgage.instrument_number, discharge.instrument_number, "DISCHARGES", 95))
            elif mortgage.creditor_name and discharge.creditor_name and mortgage.creditor_name.upper() == discharge.creditor_name.upper():
                relationships.append((mortgage.instrument_number or "", discharge.instrument_number or "", "RELATED_TO", 65))
    return raw_records, liens, relationships


class MonmouthOPRSAdapter(LienSourceAdapter):
    name = SOURCE_NAME
    source_type = "COUNTY_LAND_RECORDS"

    def __init__(self, client: httpx.AsyncClient | None = None):
        self.client = client

    async def search_property(self, identity: PropertyIdentity) -> list[LienRecord]:
        result = await self.search_property_with_raw(identity)
        return result[0]

    async def search_property_with_raw(self, identity: PropertyIdentity):
        if identity.county.strip().lower() != "monmouth":
            raise MonmouthSourceError("Monmouth OPRS can only search Monmouth County properties")
        client = self.client or httpx.AsyncClient(
            headers={"User-Agent": "SheriffSalePreScreen/1.0 (public-record research)"},
            follow_redirects=True,
            timeout=45,
        )
        close_client = self.client is None
        try:
            response = await client.get(MONMOUTH_OPRS_URL)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            form = soup.find("form", id="aspnetForm")
            if form is None:
                raise MonmouthSourceError("Public search form was not returned")
            data = {
                item.get("name"): item.get("value", "")
                for item in form.select("input[type=hidden][name]")
            }
            if identity.block and identity.lot and identity.municipality:
                data.update({
                    "ctl00$ContentPlaceHolder1$ddlMunTab4": identity.municipality.upper(),
                    "ctl00$ContentPlaceHolder1$txtBlockTab4": identity.block,
                    "ctl00$ContentPlaceHolder1$txtLotTab4": identity.lot,
                    "ctl00$ContentPlaceHolder1$btnSearchTab4": "Search",
                    "hidCurrTab": "2",
                })
            else:
                owner = next(iter(identity.current_owners), "")
                last_name = normalize_name(owner).split()[-1] if owner else ""
                if not last_name:
                    raise MonmouthSourceError("Block/lot or an owner name is required for Monmouth OPRS")
                data.update({
                    "ctl00$ContentPlaceHolder1$txtLastNameTab1": last_name,
                    "ctl00$ContentPlaceHolder1$btnSearchTab1": "Search",
                    "hidCurrTab": "1",
                })
            result = await client.post(MONMOUTH_OPRS_URL, data=data)
            result.raise_for_status()
            if any(token in result.text.lower() for token in ("captcha", "access denied", "request blocked")):
                raise MonmouthSourceError("Public source reported an access challenge")
            raw, liens, relationships = parse_oprs_results(result.text, MONMOUTH_OPRS_URL, identity)
            return liens, raw, relationships
        except (httpx.HTTPError, MonmouthSourceError):
            raise
        finally:
            if close_client:
                await client.aclose()
