"""Conservative, evidence-preserving court PDF parsing; ambiguity needs review."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from decimal import Decimal
from io import BytesIO

from pypdf import PdfReader

from .counties import COUNTIES, County

QUEENS = COUNTIES["queens"]

PARSER_VERSION = "queens-notice-v1"
INDEX = re.compile(r"(?<!\d)(\d{5,6})\s*[/‐‑–-]\s*((?:19|20)\d{2})(?!\d)")
MONTH = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
DATE = rf"(?:{MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+20\d{{2}}|\d{{1,2}}/\d{{1,2}}/20\d{{2}})"


def indices(text: str) -> list[str]:
    return sorted({f"{number}/{year}" for number, year in INDEX.findall(text)})


def pdf_text(body: bytes) -> str:
    if not body.startswith(b"%PDF-"):
        raise ValueError("Response is not a PDF")
    reader = PdfReader(BytesIO(body))
    if reader.is_encrypted:
        raise ValueError("Encrypted PDF requires review")
    result = "\n".join(page.extract_text() or "" for page in reader.pages)
    if len(result.strip()) < 30:
        raise ValueError("PDF has no usable text; operator OCR/review required")
    return result


def calendar_cases(text: str, county: County = QUEENS) -> list[str]:
    if not re.search(county.names, text, re.I):
        raise ValueError(f"Calendar does not identify {county.name}")
    found = indices(text)
    if not found and not re.search(r"no (?:cases|records|results)", text, re.I):
        raise ValueError("Calendar has no recognizable case indices")
    return found


def parse_notice(text: str, case: str, url: str, body_hash: str, county: County = QUEENS) -> dict:
    flat = re.sub(r"\s+", " ", text).strip()
    errors = []
    if indices(flat) != [case]:
        errors.append("case_index_missing_or_ambiguous")
    if not re.search(county.names, flat, re.I):
        errors.append("county_not_confirmed")
    if not re.search(r"NOTICE\s+OF\s+(?:FORECLOSURE\s+)?SALE", flat, re.I):
        errors.append("not_notice_of_sale")
    # Never confuse the auction venue with the premises being sold.
    addresses = re.findall(
        r"(?:premises\s+(?:known\s+as|located\s+at)|property\s+(?:known\s+as|located\s+at))\s*:?\s*"
        r"(\d[\w\s.,#/-]{4,180}?),\s*(?:NY|New York)\s*(\d{5})?\b", flat, re.I)
    addresses = list(dict.fromkeys(addresses))
    street = city = zip_code = None
    if len(addresses) == 1 and "," in addresses[0][0]:
        street, city = (s.strip(" ,.") for s in addresses[0][0].rsplit(",", 1))
        zip_code = addresses[0][1] or None
    if not street or not city:
        errors.append("property_address_missing_or_ambiguous")
    dates = []
    # Anchor to the sale verb, not the judgment or filing dates.
    for match in re.finditer(r"(?:sell\s+at\s+public\s+auction|sale\s+will\s+be\s+held|auction\s+will\s+be\s+held)(.{0,600}?)(?:premises|property\s+known|$)", flat, re.I):
        for value in re.findall(DATE, match.group(1), re.I):
            clean = re.sub(r"(\d)(st|nd|rd|th)", r"\1", value, flags=re.I).replace(",", "")
            for fmt in ("%B %d %Y", "%m/%d/%Y"):
                try:
                    dates.append(datetime.strptime(clean, fmt).date().isoformat())
                    break
                except ValueError:
                    continue
    dates = sorted(set(dates))
    if len(dates) != 1:
        errors.append("auction_date_missing_or_ambiguous")
    amounts = sorted({str(Decimal(v.replace(",", ""))) for v in re.findall(
        r"(?:approximate\s+)?(?:amount\s+of\s+(?:the\s+)?judgment|judgment\s+(?:amount|in\s+the\s+(?:sum|amount)\s+of))\s*(?:is|of|:)?\s*\$\s*([\d,]+\.\d{2})", flat, re.I)})
    if len(amounts) > 1:
        errors.append("conflicting_judgment_amounts")
    venue = re.search(r"sell\s+at\s+public\s+auction\s+at\s+(.{5,250}?)\s+on\s+" + DATE, flat, re.I)
    auction_time = re.search(DATE + r"\s+at\s+(\d{1,2}(?::\d{2})?\s*[ap]\.?m\.?)", flat, re.I)
    return {
        "auction_location": venue.group(1) if venue else None,
        "auction_time": auction_time.group(1).replace(".", "").upper() if auction_time else None,
        "county": county.name, "case": case, "street": street, "city": city, "zip_code": zip_code,
        "sale_date": dates[0] if len(dates) == 1 else None,
        "judgment_amount": amounts[0] if len(amounts) == 1 else None,
        "source_url": url, "pdf_sha256": body_hash, "parser_version": PARSER_VERSION,
        "sale_type": "Court foreclosure auction", "review_reasons": errors,
        "raw_text": text,
    }


def digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()
