"""Parse OCR lines of Arizona trustee-sale recordings (pipeline.ocr_engines.text_lines).

Notice of Trustee's Sale (A.R.S. 33-808(C) lists what it must state): property address,
tax parcel number, legal description, original principal balance, the deed of trust's
recording reference, sale date, time and place, beneficiary, trustee and its contact
details, and the trustee's sale (TS) number. Cancellations of the notice and trustee's
deeds upon sale are reduced to the references that tie them to a notice (TS number,
APN, instrument numbers) plus, for a deed, the sale date and price.

Never extracted: trustors' and grantees' names and mailing addresses (AGENTS.md privacy
rule). A beneficiary is kept only when it is a company; a trustee's deed records only
whether the grantee was the foreclosing beneficiary or a third party.

Every result carries `confidence` (0-1, the share of key fields found, weighted) and
`missing` (the key fields not found). OCR noise from the recorder's "Unofficial Document"
watermark is expected; values are validated (APN shape, dates after recording, ZIPs 85xxx/86xxx).
"""
import re
from datetime import date, datetime, timedelta

LABEL_END = re.compile(r"^[^|]*?:\s*\|?\s*")
# Maricopa APNs: book-map-item and an optional split letter, often printed with a check digit
# ("200-77-406-5", "133-44-047 4", "301-61-4189"), which is dropped.
APN = re.compile(r"\b(\d{3})\s?-\s?(\d{2})\s?-\s?(\d{3})([A-Z])?(?:[\s-]?\d)?\b")
MONEY = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+(?:\.\d{2})?|\d+\.\d{2})")
INSTRUMENT = re.compile(r"(?i)(?:instrument|document|doc\.?|recording)\s*(?:no\.?|number|#)?\s*[:.]?\s*(\d{4})-?(\d{7})\b"
                        r"|\b(?:in|as)\s+(20\d{2})-(\d{7})\b")
BARE_INSTRUMENT = re.compile(r"\b(19\d{2}|20\d{2})-?(\d{7})\b")
DATE = r"(\d{1,2}/\d{1,2}/\d{4}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})"
SALE_WHEN = re.compile(DATE + r"\s*,?\s*(?:at|@)?\s*(\d{1,2}:\d{2})\s*([AP])\.?\s?M\b", re.I)
TIME_THEN_DATE = re.compile(r"\b(\d{1,2}:\d{2})\s*([AP])\.?\s?M\.?\s*,?\s*(?:on\s+)?" + DATE, re.I)
ADDRESS = re.compile(r"(?P<street>\d{1,6}[A-Z]?\s+[^|,]{3,60}?)\s*,?\s+(?P<city>[A-Za-z][A-Za-z .'-]{1,30}?)\s*,?\s+"
                     r"(?:AZ|Arizona)\.?\s*,?\s*(?P<zip>8[56]\d{3})(?:-\d{4})?\b")
PHONE = re.compile(r"\(?\b(\d{3})\)?[\s.-]*(\d{3})[\s.-](\d{4})\b")
WEBSITE = re.compile(r"(?i)\b((?:https?://)?(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|us)(?:/[\w./-]*)?)")
COMPANY = re.compile(r"(?i)\b(LLC|L\.L\.C|Inc|Corp|Corporation|Company|Co\.|Bank|N\.A|Trust|Mortgage|Credit Union|"
                     r"Servicing|Financial|Funding|Capital|Lending|Loan|Association|Fund|Agency|P\.A|P\.C|PLLC|LLP|"
                     r"Solutions|Recon|Services|Title|Escrow|Federal|Investments?|Holdings|Partners|LP)\b")
SALE_PLACE = re.compile(r"(?i)(main entrance|courtyard|front entrance|entrance)[^.|]{0,120}?Superior Court"
                        r"[^.|]{0,80}?(201\s+W(?:est|\.)?\s+Jefferson[^.|]{0,40}?85003)")
LEGAL = re.compile(r"(?i)\b(?:Lot|Unit|Parcel)\s+[\w-]+[^|]{0,200}?Book\s+\d+\s+of\s+Maps,?\s+Page\s+\d+")
TS_LABEL = re.compile(r"(?i)(?:T\.?S\.?\s*(?:No\.?|Number|#|/File)|Trustee'?s?\s+Sale\s+No\.?|File\s+ID\.?\s*:?\s*#?)\s*[:.]?\s*"
                      r"([A-Z0-9][A-Z0-9-]{3,30})")
NOTICE_WEIGHTS = {"address": 0.3, "apn": 0.2, "sale_date": 0.25, "original_principal": 0.1, "deed_of_trust": 0.1,
                  "trustee": 0.05}


def joined(lines: list[str]) -> str:
    return " ".join(line.replace(" | ", " ") for line in lines)


def parse_date(value: str) -> date | None:
    value = value.replace(".", "").replace(",", "").strip()
    for pattern in ("%m/%d/%Y", "%B %d %Y", "%b %d %Y"):
        try:
            return datetime.strptime(value.replace("Sept ", "Sep "), pattern).date()
        except ValueError:
            continue
    return None


def money(text: str) -> float | None:
    found = MONEY.search(text)
    return float(found.group(1).replace(",", "")) if found else None


def apn(text: str) -> str | None:
    found = APN.search(text)
    return f"{found.group(1)}-{found.group(2)}-{found.group(3)}{found.group(4) or ''}" if found else None


def instruments(text: str, exclude: str = "") -> list[str]:
    """Recording numbers cited in the text: labelled ones ("Instrument No. 2023-0385166") first, then
    any other bare 11-digit recording number (OCR often cuts the label)."""
    found = []
    for match in INSTRUMENT.finditer(text):
        year, number = (match.group(1), match.group(2)) if match.group(1) else (match.group(3), match.group(4))
        found.append(f"{year}{number}")
    found += [f"{year}{number}" for year, number in re.findall(r"\b(19\d{2}|20\d{2})(\d{7})\b", text)]
    return [number for index, number in enumerate(found) if number != exclude and number not in found[:index]]


def labelled(lines: list[str], label: re.Pattern, following: int = 3) -> str | None:
    """The value after a label: the rest of its line, else the next lines; in a two-column row
    ("Current Beneficiary | Current Trustee:") the value is the next line's piece in that column."""
    for index, line in enumerate(lines):
        pieces = line.split(" | ")
        for column, piece in enumerate(pieces):
            match = label.search(piece)
            if not match:
                continue
            rest = piece[match.end():].lstrip(" :.-")
            if column + 1 < len(pieces) and not rest and not pieces[column + 1].rstrip().endswith(":"):
                rest = pieces[column + 1]
            if len(re.sub(r"[^A-Za-z0-9]", "", rest)) >= 4:
                return rest.strip()
            below = []
            for nxt in lines[index + 1:index + 1 + following]:
                parts = nxt.split(" | ")
                below.append(parts[column] if len(pieces) > 1 and column < len(parts) else nxt)
            return "\n".join(below)
    return None


def company(value: str | None) -> str | None:
    """The first line that names a company (C/O, care-of and "as of" lines skipped)."""
    lines = (value or "").split("\n")
    for index, line in enumerate(lines):
        line = next((piece for piece in line.split(" | ") if COMPANY.search(piece)), "").strip(" ,")
        if not line or re.match(r"(?i)^(c/o|care of|\(as of|\(as shown)", line):
            continue
        if re.search(r"(?i)d/b/a$", line) and index + 1 < len(lines):
            line = f"{line} {lines[index + 1].split(' | ')[0].strip(' ,')}"
        return re.sub(r"\s{2,}", " ", line)[:120]
    return None


def address(lines: list[str]) -> dict | None:
    labels = re.compile(r"(?i)(purported\s+(street|property)\s+address|street\s+address\s+or\s+identifiable\s+location|"
                        r"purported\s+to\s+be|property\s+address|commonly\s+known\s+as|street\s+address)")
    for index, line in enumerate(lines):
        match = labels.search(line)
        if not match:
            continue
        rest = line[match.end():].replace(" | ", " ").strip(" :.-|")
        below = [piece.replace(" | ", " ").strip() for piece in lines[index + 1:index + 3]]
        # "21259 E Lords Way" / "Queen Creek, AZ 85142": the street is the whole first line.
        for street, town in ((rest, below[0] if below else ""), (below[0] if below else "", below[1] if len(below) > 1 else "")):
            city = re.match(r"^([A-Za-z][A-Za-z .'-]{1,30}?)\s*,?\s+(?:AZ|Arizona)\.?\s*,?\s*(8[56]\d{3})\b", town)
            if city and re.match(r"^\d{1,6}[A-Z]?\s+\S", street):
                return {"street": re.sub(r"\s{2,}", " ", street).strip(" .,"), "city": city.group(1).strip(" .,").title(),
                        "zip": city.group(2)}
        window = f"{rest} {' '.join(below)}"
        found = ADDRESS.search(window)
        if found:
            return clean_address(found)
    found = ADDRESS.search(joined(lines))
    return clean_address(found) if found else None


def clean_address(found: re.Match) -> dict:
    street = re.sub(r"\s{2,}", " ", found.group("street")).strip(" .,")
    return {"street": street, "city": found.group("city").strip(" .,").title(), "zip": found.group("zip")}


def sale_when(text: str, recorded: date | None) -> tuple[date | None, str | None]:
    """The first date and time of day after the recording date: "1/12/2027 at 12:00 PM",
    "on 1/28/2027 10:00 AM" or "at 12:00 PM on January 19, 2027"."""
    found = [(match.start(), match.group(1), match.group(2), match.group(3)) for match in SALE_WHEN.finditer(text)]
    found += [(match.start(), match.group(3), match.group(1), match.group(2)) for match in TIME_THEN_DATE.finditer(text)]
    for _, when, clock, half in sorted(found):
        day = parse_date(when)
        if day and (recorded is None or recorded < day <= recorded + timedelta(days=400)):
            hour, minute = clock.split(":")
            return day, f"{int(hour)}:{minute} {half.upper()}M"
    return None, None


def ts_number(lines: list[str]) -> str | None:
    for line in lines[:40]:
        found = TS_LABEL.search(line)
        if found and re.search(r"\d", found.group(1)):
            return found.group(1).rstrip("-")
    return None


def score(fields: dict, weights: dict) -> tuple[float, list[str]]:
    missing = [name for name in weights if not fields.get(name)]
    return round(sum(weight for name, weight in weights.items() if fields.get(name)), 2), missing


def parse_notice(lines: list[str], recording_number: str, recorded: date | None) -> dict:
    text = joined(lines)
    when, time = sale_when(text, recorded)
    if when is None:
        stated = re.match(DATE, (labelled(lines, re.compile(r"(?i)sale\s+date(\s+and\s+time)?\s*:")) or "").strip())
        day = parse_date(stated.group(1)) if stated else None
        when = day if day and recorded and recorded < day <= recorded + timedelta(days=400) else None
    references = instruments(text, recording_number)
    trustee_value = labelled(lines, re.compile(r"(?i)(name\s*(,|and)\s*address(\s*&\s*telephone\s*number)?\s*of\s*trustee"
                                               r"(/agent)?|current\s+trustee|^trustee)\s*:?"))
    mail_to = labelled(lines, re.compile(r"(?i)(when\s+recorded,?\s+(mail|return)\s+to|recorded\s+at\s+request\s+of)\s*:?"),
                       following=4)
    place = SALE_PLACE.search(text)
    legal = LEGAL.search(text)
    fields = {
        "address": address(lines),
        "apn": apn(labelled(lines, re.compile(r"(?i)(tax\s+parcel\s+(number|no)|a\.?\s?p\.?\s?n\.?|parcel\s+(number|no))"
                                              r"\s*(\(s\))?\s*[:.]?")) or "") or apn(text),
        "sale_date": when.isoformat() if when else None,
        "sale_time": time,
        "sale_location": ("Main entrance of the Superior Court Building, 201 W. Jefferson St., Phoenix, AZ 85003"
                          if place else None),
        "legal_description": re.sub(r"\s{2,}", " ", legal.group(0)).strip()[:400] if legal else None,
        "original_principal": money(labelled(lines, re.compile(r"(?i)original\s+principal\s+balance\s*[:;.]?")) or ""),
        "deed_of_trust": references[0] if references else None,
        "deed_of_trust_recorded": None,
        "beneficiary": company(labelled(lines, re.compile(r"(?i)(name\s+and\s+address\s+of\s+(current\s+)?beneficiary|"
                                                          r"(original/)?c?urrent\s+beneficiar\w*|^beneficiary)\s*:?"),
                                        following=3)),
        "trustee": company(trustee_value) or company(mail_to),
        "trustee_phone": None,
        "sale_info_websites": sorted({site.lower().removeprefix("http://").removeprefix("https://").rstrip("/.")
                                      for site in WEBSITE.findall(text) if "fincen" not in site.lower()}),
        "ts_number": ts_number(lines),
    }
    recorded_on = re.search(r"(?i)recorded\s+(?:on\s+)?" + DATE, text)
    if recorded_on and (day := parse_date(recorded_on.group(1))):
        fields["deed_of_trust_recorded"] = day.isoformat()
    phone_text = (trustee_value or "") + " " + text[text.lower().find("trustee"):] if trustee_value else text
    phone = PHONE.search(phone_text)
    fields["trustee_phone"] = f"({phone.group(1)}) {phone.group(2)}-{phone.group(3)}" if phone else None
    fields["confidence"], fields["missing"] = score(fields, NOTICE_WEIGHTS)
    return fields


def parse_cancellation(lines: list[str], recording_number: str) -> dict:
    text = joined(lines)
    fields = {"references": instruments(text, recording_number), "ts_number": ts_number(lines), "apn": apn(text)}
    dated = re.search(r"(?i)\bdated?\s*:\s*\|?\s*" + DATE, text)
    fields["dated"] = parse_date(dated.group(1)).isoformat() if dated and parse_date(dated.group(1)) else None
    fields["confidence"], fields["missing"] = score(fields, {"references": 0.5, "ts_number": 0.25, "apn": 0.25})
    return fields


def parse_trustee_deed(lines: list[str], recording_number: str, recorded: date | None,
                       beneficiary: str | None = None) -> dict:
    text = joined(lines)
    upon_sale = bool(re.search(r"(?i)public\s+auction|deed\s+upon\s+sale|notice\s+of\s+trustee.?s\s+sale", text))
    if not upon_sale:
        return {"upon_sale": False, "confidence": 1.0, "missing": []}
    sold = re.search(r"(?i)public\s+auction\s+on\s+" + DATE, text)
    sold_on = parse_date(sold.group(1)) if sold else None
    if sold_on and recorded and not (recorded - timedelta(days=120) <= sold_on <= recorded):
        sold_on = None
    amount = re.search(r"(?i)(?:amount\s+paid\s+by\s+the\s+grantee[^$]{0,40}?|amount\s+bid,?\s*(?:namely|being|of)?\s*|"
                       r"\bfor\s+(?:the\s+sum\s+of\s+)?)\$\s?(\d{1,3}(?:,\d{3})*[.,]\d{2})\b", text)
    fields = {"upon_sale": True, "references": instruments(text, recording_number),
              "ts_number": ts_number(lines), "apn": apn(text),
              "sold_on": sold_on.isoformat() if sold_on else None,
              "price": float(re.sub(r"[.,](\d{2})$", r"_\1", amount.group(1)).replace(",", "").replace("_", "."))
              if amount else None,
              "credit_bid": bool(re.search(r"(?i)credit\s+bid", text)) and not re.search(r"(?i)or\s+by\s+credit\s+bid\s+if", text)}
    grantee = re.search(r"(?i)\bto\s+(.{3,120}?),?\s+herein\s+called\s+.?Grantee", text)
    fields["grantee_is_company"] = bool(grantee and COMPANY.search(grantee.group(1)))
    stated = re.search(r"(?i)grantee\s+herein\s+(?:is|was)\s+(not\s+)?the\s+foreclosing\s+beneficiary", text)
    if stated:
        fields["buyer"] = "third_party" if stated.group(1) else "beneficiary"
    elif re.search(r"(?i)foreclosing\s+beneficiary,?\s+being\s+the\s+highest\s+bidder", text):
        fields["buyer"] = "beneficiary"
    else:
        fields["buyer"] = buyer_type(grantee.group(1) if grantee else None, beneficiary)
    fields["confidence"], fields["missing"] = score(fields, {"references": 0.3, "apn": 0.2, "sold_on": 0.25, "price": 0.25})
    return fields


def buyer_type(grantee: str | None, beneficiary: str | None) -> str:
    """'beneficiary' when the grantee is the foreclosing beneficiary, 'third_party' when it is not,
    'not_stated' when either is unknown. The grantee's name itself is never returned."""
    if not grantee or not beneficiary:
        return "not_stated"
    words = lambda value: {word for word in re.findall(r"[a-z0-9]+", value.lower())
                           if word not in {"llc", "inc", "na", "n", "a", "the", "as", "trustee", "for", "of", "corporation",
                                           "corp", "company", "co", "its", "and"}}
    grantee_words, beneficiary_words = words(grantee), words(beneficiary)
    if grantee_words and beneficiary_words and len(grantee_words & beneficiary_words) >= min(2, len(beneficiary_words)):
        return "beneficiary"
    return "third_party"
