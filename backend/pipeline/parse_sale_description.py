from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Optional


MONEY_VALUE = (
    r"\$?\s*("
    r"(?:\d{1,3}(?:,\s*\d{3})+|\d+)"
    r"(?:\.\d{1,2})?"
    r")"
)


@dataclass
class ParsedSaleDescription:
    judgment_amount: Optional[Decimal] = None
    estimated_upset_price: Optional[Decimal] = None
    alternate_upset_price: Optional[Decimal] = None
    daily_interest: Optional[Decimal] = None
    attorney_fees_costs: Optional[Decimal] = None

    docket_number: Optional[str] = None
    block: Optional[str] = None
    lot: Optional[str] = None
    qualifier: Optional[str] = None
    parcel_identifiers: list[dict[str, Optional[str]]] = field(default_factory=list)

    deposit_percent: Optional[Decimal] = None
    balance_due_days: Optional[int] = None
    owner_occupied: Optional[bool] = None

    parser_version: str = "monmouth-description-v3"
    upset_price_conflict: bool = False


def normalize_text(value: str) -> str:
    """Collapse line breaks and repeated spaces while preserving wording."""
    return " ".join(value.replace("\xa0", " ").split())


def money_to_decimal(value: Optional[str]) -> Optional[Decimal]:
    if not value:
        return None

    cleaned = (
        value.replace("$", "")
        .replace(",", "")
        .replace(" ", "")
        .strip()
    )

    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def search_group(
    pattern: str,
    text: str,
    group: int = 1,
) -> Optional[str]:
    match = re.search(
        pattern,
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if not match:
        return None

    return match.group(group).strip()


def extract_money_after_labels(
    text: str,
    labels: list[str],
    max_distance: int = 180,
) -> Optional[Decimal]:
    """
    Find a monetary value appearing shortly after one of the supplied labels.
    """

    for label in labels:
        pattern = (
            rf"(?:{label})"
            rf".{{0,{max_distance}}}?"
            rf"{MONEY_VALUE}"
        )

        value = search_group(pattern, text)

        amount = money_to_decimal(value)

        if amount is not None:
            return amount

    return None


def determine_owner_occupied(text: str) -> Optional[bool]:
    lower = text.lower()

    negative_patterns = (
        "not owner occupied",
        "not owner-occupied",
        "property is vacant",
        "premises are vacant",
    )

    positive_patterns = (
        "property is owner occupied",
        "property is owner-occupied",
        "owner occupied",
        "owner-occupied",
    )

    if any(pattern in lower for pattern in negative_patterns):
        return False

    if any(pattern in lower for pattern in positive_patterns):
        return True

    return None


def extract_parcel_identifiers(text: str) -> list[dict[str, Optional[str]]]:
    """Extract one or more legal parcel identifiers from the notice parcel clause."""
    renumbered = list(re.finditer(
        r"tax\s+block\s+[A-Z0-9.\-]+\s+n/k/a\s+tax\s+block\s+"
        r"([A-Z0-9.\-]+)\s*,?\s*tax\s+lot\s+([A-Z0-9.\-]+)",
        text,
        flags=re.IGNORECASE,
    ))
    if renumbered:
        return [{"block":match.group(1),"lot":match.group(2),"qualifier":None}
                for match in renumbered]
    clause = search_group(
        r"lot\s+block\s+number\s+if\s+available\s*:\s*"
        r"(.{0,500}?)(?:tax\s+map|commonly\s+known\s+as|approximate\s+dimensions)",
        text,
    )
    if not clause:
        return []
    clause = re.sub(r"^lot\s+and\s+block\s*:\s*", "", clause, flags=re.IGNORECASE)
    identifiers: list[dict[str, Optional[str]]] = []

    repeated = list(re.finditer(
        r"\blot\s+([A-Z0-9.\-]+)\s+in\s+block\s+([A-Z0-9.\-]+)",
        clause,
        flags=re.IGNORECASE,
    ))
    if repeated:
        for match in repeated:
            identifiers.append({"lot": match.group(1), "block": match.group(2), "qualifier": None})
        return identifiers

    match = re.search(
        r"\blot(?:\(s\))?\s*:?[ ]*(.+?)\s*,?\s+block\s*:?[ ]*([A-Z0-9.\-]+)",
        clause,
        flags=re.IGNORECASE,
    )
    if not match:
        return []
    lots_text, block = match.groups()
    for token in re.split(r"\s*(?:,|&|\band\b)\s*", lots_text, flags=re.IGNORECASE):
        parts = token.strip().split()
        if not parts:
            continue
        lot = parts[0]
        qualifier = parts[1] if len(parts) > 1 else None
        if re.fullmatch(r"[A-Z0-9.\-]+", lot, flags=re.IGNORECASE):
            identifiers.append({"lot": lot, "block": block, "qualifier": qualifier})
    return identifiers


def parse_sale_description(
    description: str,
) -> ParsedSaleDescription:
    text = normalize_text(description)

    estimated_upset = extract_money_after_labels(
        text,
        [
            r"estimated\s+upset\s+(?:price|amount)",
            r"estimated\s+upset\s+bid\s+amount",
            r"estimated\s+upset\s+sheriff(?:['’]s?)?\s+(?:sale\s+)?bid\s+amount",
            r"good\s+faith\s+estimated\s+upset",
            r"plaintiff(?:['’]s?)?\s+upset\s+bid(?:\s+amount)?\s+"
            r"(?:presently\s+)?approximates?",
            r"estimated\s+amount\s+required\s+to\s+satisfy",
            r"estimated\s+amount\s+due",
            r"anticipated\s+upset\s+(?:price|amount)",
        ],
    )

    alternate_upset = extract_money_after_labels(
        text,
        [
            r"approximate\s+upset\s+(?:price|amount)",
            r"approximate\s+anticipated\s+upset",
            r"approximate\s+upset\s+sum",
            r"approximate\s+sheriff\s+upset",
            r"upset\s+sheriff(?:['’]s?)?\s+(?:sale\s+)?bid\s+amount",
            r"plaintiff(?:['’]s?)?\s+upset\s+bid\s+is",
            r"upset\s+bid\s+amount",
            r"upset\s+(?:price|amount)",
        ],
        max_distance=60,
    )

    # A generic upset label can overlap a more specific estimated
    # label. Preserve a genuinely different alternate value only.
    if alternate_upset == estimated_upset:
        alternate_upset = None

    judgment = extract_money_after_labels(
        text,
        [
            r"approximate\s+judg(?:e)?ment\s+amount",
            r"judg(?:e)?ment\s+amount",
            r"amount\s+of\s+judg(?:e)?ment",
            r"final\s+judg(?:e)?ment",
        ],
    )

    daily_interest = extract_money_after_labels(
        text,
        [
            r"interest\s+(?:accrues|accruing)\s+at",
            r"interest\s+at",
            r"per\s+diem\s+interest",
            r"daily\s+interest",
        ],
        max_distance=100,
    )

    attorney_fees = extract_money_after_labels(
        text,
        [
            r"attorney(?:'s)?\s+fees\s+and\s+costs",
            r"attorneys?\s+fees",
            r"legal\s+fees\s+and\s+costs",
        ],
    )

    docket_number = search_group(
        r"(?:docket|case)\s*(?:number|no\.?|#)?\s*[:#]?\s*"
        r"([A-Z0-9\-:/]+)",
        text,
    )

    parcel_identifiers = extract_parcel_identifiers(text)
    if not parcel_identifiers:
        generic = re.search(
            r"\bblock\s*:?[ ]*([A-Z0-9.\-]+)\s*,?\s+lot\s*:?[ ]*([A-Z0-9.\-]+)",
            text,
            flags=re.IGNORECASE,
        )
        if generic:
            parcel_identifiers = [{
                "block": generic.group(1).rstrip(".-,"),
                "lot": generic.group(2).rstrip(".-,"),
                "qualifier": None,
            }]
    primary_parcel = parcel_identifiers[0] if len(parcel_identifiers) == 1 else {}
    block = primary_parcel.get("block")
    lot = primary_parcel.get("lot")

    qualifier = primary_parcel.get("qualifier") or search_group(
        r"\bqualifier\s*(?:number|no\.?|#)?\s*[:#]?\s*"
        r"([A-Z0-9](?:[A-Z0-9.\-]*[A-Z0-9])?)",
        text,
    )

    deposit = search_group(
        r"(?:deposit|required\s+deposit)"
        r".{0,80}?(\d+(?:\.\d+)?)\s*%",
        text,
    )

    balance_days = search_group(
        r"(?:balance|remaining\s+balance)"
        r".{0,100}?(?:within|in|due\s+in)\s+"
        r"(\d+)\s+(?:calendar\s+)?days",
        text,
    )

    upset_conflict = False

    if estimated_upset and alternate_upset:
        difference = abs(estimated_upset - alternate_upset)
        larger = max(estimated_upset, alternate_upset)

        upset_conflict = (
            difference > Decimal("1000")
            and difference / larger > Decimal("0.01")
        )

    return ParsedSaleDescription(
        judgment_amount=judgment,
        estimated_upset_price=estimated_upset,
        alternate_upset_price=alternate_upset,
        daily_interest=daily_interest,
        attorney_fees_costs=attorney_fees,
        docket_number=docket_number,
        block=block,
        lot=lot,
        qualifier=qualifier,
        parcel_identifiers=parcel_identifiers,
        deposit_percent=money_to_decimal(deposit),
        balance_due_days=(
            int(balance_days)
            if balance_days
            else None
        ),
        owner_occupied=determine_owner_occupied(text),
        upset_price_conflict=upset_conflict,
    )


def parsed_to_json_dict(
    parsed: ParsedSaleDescription,
) -> dict:
    result = asdict(parsed)

    for key, value in result.items():
        if isinstance(value, Decimal):
            result[key] = str(value)

    return result
