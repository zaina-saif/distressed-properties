"""Parse NY Supreme Court foreclosure-auction documents saved by the operator.

Three layouts, recognised from their text (OCR'd when scanned):
  - Notice of Sale (one property; Kings posts one per property): index number,
    premises, auction date/time/place, block/lot, approximate judgment, referee,
    plaintiff and plaintiff's attorney.
  - Bronx "Calendar Summary Report" (WebCivil auction calendar, many cases):
    calendar date, index number, premises, block/lot, referee, plaintiff.
  - Manhattan "Foreclosure Auction Part" list: index number, parties, time and
    outcome, but no property address.

Parsers return records plus a list of problems; a record with a problem is
never loaded (see load_ny_court_pdfs).
"""
from __future__ import annotations

import re
from datetime import date, datetime

BOROUGHS = {  # county -> city used in addresses
    "Kings": "Brooklyn", "Bronx": "Bronx", "New York": "New York", "Queens": None, "Richmond": "Staten Island",
}
INDEX = re.compile(r"(?<!\d)(\d{3,6})\s*/\s*((?:19|20)\d{2})(?:E\b)?")
MONEY = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
DATE = rf"(?:(?:{MONTHS}|[a-z]{{3,8}})\s+\d{{1,2}},?\s+20\d{{2}}|\d{{1,2}}/\d{{1,2}}/20\d{{2}})"
STREET_END = re.compile(r"\b(?:Street|St|Avenue|Ave|Place|Pl|Road|Rd|Boulevard|Blvd|Court|Ct|Lane|Ln|Drive|Dr|"
                        r"Terrace|Parkway|Pkwy|Way|Walk|Plaza|Square|Concourse|Loop|Oval|Path|Row|Crescent|Broadway)"
                        r"\.?(?:\s*(?:#|Apt\.?|Unit)\s*[\w-]+)?$", re.I)
TIME = r"(\d{1,2}(?::\d{2})?\s*[AaPp]\.?\s*[Mm]\.?)"
CITY_NAMES = r"Brooklyn|Bronx|New York|Staten Island|[A-Z][a-z]+(?: [A-Z][a-z]+)?"


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def to_date(value: str) -> date | None:
    value = value.replace(",", "")
    # OCR clips the page edge ("tober 15, 2026"): complete a unique month ending.
    month = re.match(r"([A-Za-z]{3,9})\s", value)
    if month and month.group(1).lower() not in MONTHS.lower().split("|"):
        options = [m for m in MONTHS.split("|") if m.lower().endswith(month.group(1).lower())]
        if len(options) == 1:
            value = options[0] + value[month.end(1):]
    for pattern in ("%B %d %Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, pattern).date()
        except ValueError:
            continue
    return None


def index_number(number: str, year: str) -> str:
    return f"{int(number)}/{year}"


def ordinal_case(street: str) -> str:
    """'31St Street' -> '31st Street' after title-casing."""
    return re.sub(r"(\d)(St|Nd|Rd|Th)\b", lambda m: m.group(1) + m.group(2).lower(), street)


def kind(text: str) -> str:
    body = flat(text)
    if re.search(r"Calendar Summary Report", body, re.I):
        return "calendar_summary"
    if re.search(r"FORECLOSURE AUCTION PART", body, re.I):
        return "auction_part_list"
    if re.search(r"NOTICE OF [A-Z ]{0,30}SALE|will sell at publi?c?\s+a?uction", body, re.I):
        return "notice_of_sale"
    return "unknown"


def split_address(raw: str, default_city: str | None) -> tuple[str | None, str | None, str | None]:
    """'1312 Myrtle Avenue, Brooklyn, NY 11221' -> street, city, ZIP (OCR may garble "NY" to "N. .")."""
    value = flat(raw).strip(" ,.;")
    match = re.match(rf"(.+?),\s*({CITY_NAMES})\b,?\s*(?:New York|N[\s.]*Y?\.?)\.?,?\s*(\d{{5}})?", value, re.I)
    if match:
        street, city, zip_code = match.group(1), match.group(2).title(), match.group(3)
        if street.isupper():
            street = ordinal_case(street.title())
    else:
        street, city, zip_code = value, default_city, None
    street = re.sub(r"\s*,\s*$", "", street).strip()
    # OCR clips the right margin, so keep only the first "a/k/a" alternative.
    street = re.split(r"\s+a/?k/?a\s+", street, maxsplit=1, flags=re.I)[0].strip(" ,")
    if city and city.lower() == "new york" and default_city and default_city != "New York":
        city = default_city
    return street or None, city, zip_code


def parse_notice_of_sale(text: str, county: str, file_address: str | None = None) -> tuple[dict, list[str]]:
    """file_address: the court's name for the notice file ("644 LORIMER STREET #6"),
    used when OCR clipped the street name in the notice body."""
    body = flat(text)
    problems = []
    found = {index_number(*m) for m in INDEX.findall(" ".join(re.findall(r"INDEX\s*(?:NO\.?|#|NUMBER)\s*:?\s*[\d/ ]+", body, re.I)))}
    if len(found) != 1:
        problems.append("index_number_missing_or_ambiguous")
    sale = re.search(rf"(?:will\s+sell|publi\w*\s+a?uction).{{0,220}}?\bon\s+({DATE})(?:\s*,?\s*at\s+{TIME})?", body, re.I)
    sale_date = to_date(sale.group(1)) if sale else None
    if not sale_date:
        problems.append("auction_date_missing")
    premises = re.search(r"premises\s+(?:known\s+as|located\s+at)\s*:?\s*(\d.{4,160}?(?:\d{5}|(?=;)|(?=\.\s)))", body, re.I)
    street = city = zip_code = None
    address_source = "notice"
    if premises:
        street, city, zip_code = split_address(premises.group(1), BOROUGHS.get(county))
    if not (street and re.match(r"\d", street) and STREET_END.search(street)) and file_address \
            and re.match(r"\d+\s+\w", file_address):
        street, address_source = ordinal_case(" ".join(file_address.split()).title()), "court_file_name"
        city = BOROUGHS.get(county) or city
        zip_code = zip_code or (re.search(r"\b(1\d{4})\b", premises.group(1)).group(1)
                                if premises and re.search(r"\b(1\d{4})\b", premises.group(1)) else None)
    if not street or not re.match(r"\d", street):
        problems.append("premises_address_missing")
    postponed = re.search(rf"original\s+sale\s+was\s+scheduled\s+for\s+({DATE})", body, re.I)
    block_lot = re.search(r"Block\s*:?\s*(\d{1,5})\W{0,5}(?:and\s+)?Lots?\s*:?\s*(\d{1,4})", body, re.I)
    judgment = re.search(r"amount\s+of\s+(?:the\s+)?(?:current\s+)?(?:judgment(?:\s+lien)?|lien)\s*(?:is|of|:)?\s*\$\s*([\d,]+(?:\.\d{2})?)", body, re.I)
    # The referee signs at the end: "Mark Longo, Esq., Referee" / "Leonard C. Spector, Referee".
    referees = list(re.finditer(r"([A-Z][A-Za-z.'\-]*(?:\s+[A-Z][A-Za-z.'\-]*){1,3}),\s*(?:(?i:Esq)\.?\s*,?\s*[-–]?\s*)?(?i:Referee)\b\.?", body))
    referee = referees[-1].group(1) if referees else None
    # The plaintiff's attorney follows the referee's signature.
    attorney = re.match(r"\s*(.{5,120}?)(?:,\s*\d|\s+Attorneys?\s*(?:\(s\))?\s+for\s+Plaintiff|\s+\d)",
                        body[referees[-1].end():]) if referees else None
    place = re.search(r"auction\s+(?:at|in)\s+(?:the\s+)?(.{5,120}?)\s+on\s+" + DATE, body, re.I)
    plaintiff = (re.search(r"wherein\s+(.{3,250}?)\s+is\s+the\s+Plaintiff", body, re.I)
                 or re.search(r"COUNTY OF \w+\W+(.{5,300}?),?\s*Plaintiffs?\b", body, re.I))
    record = {
        "document": "notice_of_sale", "county": county,
        "index_number": next(iter(found)) if len(found) == 1 else None,
        "sale_date": sale_date.isoformat() if sale_date else None,
        "sale_time": flat(sale.group(2)) if sale and sale.group(2) else None,
        "sale_place": place.group(1).strip(" ,") if place else None,
        "street": street, "city": city, "zip_code": zip_code, "address_source": address_source,
        "postponed_from": to_date(postponed.group(1)).isoformat() if postponed and to_date(postponed.group(1)) else None,
        "block": block_lot.group(1) if block_lot else None, "lot": block_lot.group(2) if block_lot else None,
        "judgment": float(judgment.group(1).replace(",", "")) if judgment else None,
        "referee": referee,
        "plaintiff": plaintiff.group(1).strip() if plaintiff else None,
        "plaintiff_attorney": attorney.group(1).strip(" ,") if attorney else None,
    }
    return record, problems


def parse_calendar_summary(text: str, county: str) -> list[tuple[dict, list[str]]]:
    """WebCivil Calendar Summary Report: one block per case, each under its calendar date."""
    results = []
    body = text or ""
    # Calendar dates in order; each case belongs to the latest date header before it.
    headers = [(m.start(), to_date(m.group(1))) for m in re.finditer(r"Calendar Date:\s*(\d{1,2}/\d{1,2}/20\d{2})", body)]
    cases = list(re.finditer(r"Index\s*#\s*:?\s*(\d{3,6})\s*/\s*((?:19|20)\d{2})", body))
    for position, match in enumerate(cases):
        end = cases[position + 1].start() if position + 1 < len(cases) else len(body)
        start = cases[position - 1].end() if position else 0
        block, before = body[match.start():end], body[start:match.start()]
        problems = []
        calendar_date = next((d for p, d in reversed(headers) if p < match.start()), None)
        if not calendar_date:
            problems.append("calendar_date_missing")
        premises = re.search(r"Premises\s*:?\s*(.{5,160}?)(?:\n|Block\s*:)", block, re.I | re.S)
        street = city = zip_code = None
        if premises:
            street, city, zip_code = split_address(premises.group(1), BOROUGHS.get(county))
        if street and sum(c.isupper() for c in street) > sum(c.islower() for c in street):
            street = ordinal_case(street.title())
        if not street or not re.match(r"\d", street):
            problems.append("premises_address_missing")
        block_lot = re.search(r"Block\s*:?\s*(\d{1,5})\s*;?\s*Lot\s*:?\s*(\d{1,4})", block, re.I)
        referee = re.search(r"Referee\s*:?\s*([^\n]{3,80})", block, re.I)
        plaintiff = re.findall(r"\n([^\n]{3,120}?)\s*\(\d+\s+For\s+Part", before)
        results.append(({
            "document": "calendar_summary", "county": county,
            "index_number": index_number(match.group(1), match.group(2)),
            "sale_date": calendar_date.isoformat() if calendar_date else None,
            "street": street, "city": city, "zip_code": zip_code,
            "block": block_lot.group(1) if block_lot else None, "lot": block_lot.group(2) if block_lot else None,
            "judgment": None,
            "referee": re.split(r"\s*[,(]?\s*Esq|\s+\(?\d{3}\)?[\s-]\d{3}", referee.group(1), flags=re.I)[0].strip(" ,.-") if referee else None,
            "plaintiff": plaintiff[-1].strip() if plaintiff else None,
        }, problems))
    return results


def parse_auction_part_list(text: str, county: str) -> list[tuple[dict, list[str]]]:
    """Manhattan Foreclosure Auction Part list: no premises, so every entry is
    reported (not loaded) until an address source is joined by index number."""
    body = text or ""
    day = re.search(rf"(?:Monday|Tuesday|Wednesday|Thursday|Friday)\s+((?:{MONTHS})\s+\d{{1,2}},?\s+20\d{{2}})", body)
    sale_date = to_date(day.group(1)) if day else None
    results = []
    for entry in re.split(r"-{20,}", body):
        match = re.search(r"(\d{5,6})/((?:19|20)\d{2})\s*-\s*(.+?)\s+vs\.", entry, re.S)
        if not match:
            continue
        outcome = re.search(r"Outcome:\s*([^\n]+)", entry)
        results.append(({
            "document": "auction_part_list", "county": county,
            "index_number": index_number(match.group(1), match.group(2)),
            "sale_date": sale_date.isoformat() if sale_date else None,
            "plaintiff": flat(match.group(3)), "street": None, "city": None, "zip_code": None,
            "judgment": None, "referee": None,
            "outcome": outcome.group(1).strip() if outcome else None,
        }, ["premises_address_not_published"]))
    return results
