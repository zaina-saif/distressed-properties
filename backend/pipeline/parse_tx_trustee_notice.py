"""Parse the OCR text of a Texas Notice of Trustee's (or Foreclosure) Sale.

Every law firm uses its own layout, and OCR reads two-column forms out of order, so
labels and values are often far apart. The parser therefore looks for the shapes it
needs instead of fixed positions:

- street address: a "<number> <street>, <city>, TX 77xxx" line (or a street line
  followed by its city line), with a Harris-area ZIP. The sale venue and addresses of
  law firms, trustees, lenders and servicers are left out. An address on or right after
  a "Property Address" / "Commonly known as" label is "labeled"; otherwise a single
  remaining candidate is "inferred", and several different ones are left unresolved.
- legal description, with lot, block and subdivision for matching appraisal records.
- the original principal of the loan (not the amount owed, not an opening bid).
- the foreclosing lender (current mortgagee, beneficiary or payee).
- whether the notice forecloses an owners' association assessment lien.

Borrower and grantor names are never returned.
"""
import difflib
import re

PARSER_VERSION = "tx_trustee_notice_v1"

ZIP = r"(7[7][0-9OS]{3})"
STREET = r"(\d{1,6}[A-Z]?(?:-[A-Z0-9]+)?\s+(?:[NSEW]\.?\s+)?[A-Za-z0-9][A-Za-z0-9 .'/&\-]{2,60}?(?:,?\s+(?:#|Unit|Apt\.?|Bldg\.?)\s*[\w-]+)?)"
CITY = r"([A-Za-z][A-Za-z .']{2,30}?)"
STATE = r"(?:TX|Texas|TEXAS|Tx)\.?"
ONE_LINE = re.compile(rf"{STREET}\s*,?\s+{CITY}\s*,?\s+{STATE}\s*,?\s*{ZIP}\b")
CITY_LINE = re.compile(rf"^\s*{CITY}\s*,?\s+{STATE}\s*,?\s*{ZIP}\b")
STREET_LINE = re.compile(rf"^\s*{STREET}\s*,?\s*$")
LABEL = re.compile(r"(?i)commonly\s+known|property\s+address|street\s+address|address\s+of\s+(?:the\s+)?property"
                   r"|also\s+known\s+as|known\s+as|more\s+commonly|physical\s+address|property\s+located\s+at")
# Lines naming someone else's address: law firms, trustees, lenders, servicers, the venue.
NOT_PROPERTY = re.compile(r"(?i)\bsu?ite\b|\bsute\b|\bste\.?\s*\d|\bfloor\b|p\.?\s*o\.?\s*box|c/o\b|whose\s+address|mailing\s+address"
                          r"|servicer|trustee|payee|beneficiary|holder|mortgagee|lender|attorney|\blaw\b|\bllp\b|\bpllc\b"
                          r"|\bp\.c\.|event\s+center|ballroom|knight\s+r(?:oa)?d|courthouse|caroline|declarant|my\s+name")
STREET_WORDS = re.compile(r"(?i)\b(?:st|street|dr|drive|rd|road|ln|lane|ct|court|cir|circle|blvd|boulevard|ave|avenue|way|trl|"
                          r"trail|pl|place|pkwy|parkway|loop|hwy|highway|fwy|freeway|cv|cove|xing|crossing|bnd|bend|pt|point|"
                          r"holw|hollow|tr|ter|terrace|row|run|path|walk|park|creek|ridge|glen|oaks?|meadows?|vis|vista|sq|"
                          r"square|expy|grv|grove|hts|heights|est|estates|landing|pass|spur|view|green|canyon|hill|hills|"
                          r"forest|lake|lakes|springs?|valley|manor|chase|gate|circle)\b\.?")
MONEY = r"[\$S§]\s?([\d]{1,3}(?:[,.]\d{3})+(?:\.\d{2})?|\d+\.\d{2})"
PRINCIPAL = [
    re.compile(rf"(?i)original\s+principal(?:\s+amount)?(?:\s+of)?\s*[:.]?\s*{MONEY}"),
    re.compile(rf"(?i)(?:original|principal)\s+(?:principal\s+)?amount\s+of\s*{MONEY}"),
    re.compile(rf"(?i)in\s+the\s+(?:original\s+)?(?:principal\s+)?(?:sum|amount)\s+of\s*{MONEY}"),
    re.compile(rf"(?i)principal\s+amount\s*:?\s*{MONEY}"),
]
LENDER = [
    re.compile(r"([A-Z][A-Za-z0-9&.,' -]{2,90}?),?\s+whose\s+address\s+(?:is|1s)\s+.{0,200}?,?\s+is\s+the\s+current\s+mortgagee"),
    re.compile(r"(?im)^\s*current\s+(?:mortgagee|beneficiary(?:\s*/\s*mortgagee)?|payee|holder)\s*[:.]\s*(\S.{2,200})$"),
    re.compile(r"(?i)([A-Z][\w&.,'()/ -]{2,250}?),?\s+is\s+the\s+current\s+mortgagee"),
    re.compile(r"(?i)transferred\s+to\s+([A-Z][\w&.,' -]{2,90}?)\s*;"),
    re.compile(r"(?i)grants\s+to\s+([A-Z][\w&.,' -]{2,90}?)\s*\(\s*[\"“]lender"),
    re.compile(r"(?im)^\s*lender\s*:\s*(\S.{2,200})$"),
]
ORGANISATION = re.compile(r"(?i)\b(?:bank|banc|mortgage|llc|l\.l\.c|inc|corp|corporation|company|co\.|n\.\s?a\b|fsb|trust|"
                          r"association|servic\w*|lending|loans?\b|financial|finance|fund\w*|credit|capital|secretary|"
                          r"federal|housing|lp|ltd|partners\w*|homes?\b|investments?|holdings?|savings|authority)")
# A match that ran over the sentence naming the borrower, or a role rather than a name.
NOT_A_LENDER = re.compile(r"(?i)\b(?:executed|securing|promissory|deed\s+of\s+trust|grantor|borrower|substitute\s+trustee|"
                          r"obligations?\s+secured|clerk'?s\s+file|property\s+records)\b|^(?:loan|loan\s+servicing\s+agent)$")
LEGAL_START = re.compile(r"(?i)\b(?:lots?\s+[\w(]|tract\s+[\w(]|unit\s+[\w(]|condominium\s+unit|being\s+(?:a|all|that|lot)|"
                         r"all\s+that\s+certain|field\s+notes|reserve\s+[\w(])")
LEGAL_END = re.compile(r"(?i)according\s+to\s+the\s+(?:map|plat)|\brecorded\s+(?:in|at|under)|\.\s+\d\.\s|\n\s*\d\.\s")
LOT = re.compile(r"(?i)\blot\s+(?:[a-z\-]+\s*)?\(?\s*(\d+[A-Z]?)\s*\)?")
BLOCK = re.compile(r"(?i)\bblock\s+(?:[a-z\-]+\s*)?\(?\s*(\d+[A-Z]?)\s*\)?")
SUBDIVISION = re.compile(r"(?i)\b(?:block|lot)\s+[^,]*?,?\s+(?:of\s+)?(?:the\s+)?(?:replat\s+of\s+|amending\s+plat\s+of\s+)?"
                         r"([A-Z0-9][A-Z0-9 &'.\-]{3,60}?)(?:,?\s+(?:SEC(?:TION)?\.?|SECTION)\s+([\w()\-]+))?"
                         r"\s*,?\s+(?:an?\s+)?(?:subdivision|addition|amending|partial|replat|according)")
# Mailing cities in and around Harris County, to correct OCR slips ("Mouston").
CITIES = ["Houston", "Katy", "Spring", "Humble", "Cypress", "Tomball", "Pasadena", "Baytown", "Channelview", "Crosby",
          "Kingwood", "Friendswood", "La Porte", "Seabrook", "Webster", "Bellaire", "Missouri City", "Pearland",
          "Hockley", "Huffman", "Highlands", "South Houston", "Galena Park", "Jacinto City", "Deer Park",
          "Jersey Village", "Atascocita", "Waller", "Magnolia", "Sugar Land", "Stafford", "Nassau Bay", "Kemah",
          "League City", "Dickinson", "Richmond", "Rosenberg", "Fulshear", "Conroe", "The Woodlands", "Porter",
          "New Caney", "Dayton", "Mont Belvieu", "Barrett", "Sheldon", "Aldine", "Klein", "Hufsmith", "Fresno",
          "Manvel", "Alvin", "Brookshire", "Pinehurst", "El Lago", "Taylor Lake Village", "Shoreacres", "Morgan's Point"]
HOA = re.compile(r"(?i)(?:home\s*owners?|property\s+owners?|community|maintenance|civic|condominium|owners)\s*'?\s*association")


def _zip(value: str) -> str:
    return value.replace("O", "0").replace("S", "5")


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" ,.;:")


def _fix_split(street: str, city: str) -> tuple[str, str]:
    """'20519 SPRING' + 'LILAC LN SPRING' (no comma after the street) -> '20519 SPRING LILAC LN' + 'SPRING';
    '951-1 11 7815 PONTE MARIA TRAIL' -> '7815 PONTE MARIA TRAIL'."""
    words = city.split()
    ends = [i for i, word in enumerate(words[:-1]) if STREET_WORDS.fullmatch(word)]
    if ends:
        street, city = f"{street} {' '.join(words[:ends[-1] + 1])}", " ".join(words[ends[-1] + 1:])
    starts = [m.start() for m in re.finditer(r"\b\d{1,6}[A-Z]?\s+(?=[A-Za-z])", street)
              if STREET_WORDS.search(street[m.start():])]
    return (street[starts[-1]:] if starts else street), city


def _good_street(street: str) -> bool:
    return bool(STREET_WORDS.search(street)) and not re.search(r"(?i)\b(?:lot|block|section|volume|page|film|code)\b", street)


def address_candidates(text: str) -> list[dict]:
    lines = text.splitlines()
    found = []
    for index, line in enumerate(lines):
        context = " ".join(lines[max(0, index - 1):index + 1])
        labeled = bool(LABEL.search(line)) or bool(index and LABEL.search(lines[index - 1]))
        for match in ONE_LINE.finditer(line):
            street, city, zip_code = match.groups()
            street = LABEL.sub("", street).lstrip(" :")
            # A label vouches for its line; otherwise the line before can name whose address it is.
            above = lines[index - 1] if index and not labeled else ""
            found.append({"street": street, "city": city, "zip": zip_code, "line": index, "labeled": labeled,
                          "excluded": bool(NOT_PROPERTY.search(line) or NOT_PROPERTY.search(above))})
        city_line = CITY_LINE.match(line)
        if city_line and index:
            street_match = STREET_LINE.match(LABEL.sub("", lines[index - 1]).lstrip(" :"))
            if street_match:
                prior = lines[index - 2] if index > 1 else ""
                found.append({"street": street_match.group(1), "city": city_line.group(1), "zip": city_line.group(2),
                              "line": index - 1, "labeled": bool(LABEL.search(lines[index - 1]) or LABEL.search(prior)),
                              "excluded": bool(NOT_PROPERTY.search(context) or NOT_PROPERTY.search(prior))})
    result = []
    for candidate in found:
        street, city = _fix_split(_clean(candidate["street"]), _clean(candidate["city"]))
        city = city.title()
        candidate["street"] = _clean(street)
        letters = re.sub(r"[^A-Za-z' ]", "", city).title()
        candidate["city"] = (difflib.get_close_matches(letters, CITIES, n=1, cutoff=0.6) or [city])[0]
        candidate["zip"] = _zip(candidate["zip"])
        if candidate["zip"][:3] in {"770", "771", "772", "773", "774", "775"} and _good_street(candidate["street"]):
            result.append(candidate)
    return result


def pick_address(text: str) -> tuple[dict | None, str | None, int]:
    """(address, how it was found, number of distinct candidates)."""
    candidates = [candidate for candidate in address_candidates(text) if not candidate["excluded"]]
    distinct = {}
    for candidate in candidates:
        key = (candidate["street"].upper(), candidate["zip"])
        if key not in distinct or candidate["labeled"]:
            distinct[key] = candidate
    labeled = [candidate for candidate in distinct.values() if candidate["labeled"]]
    if len(labeled) == 1:
        return labeled[0], "labeled", len(distinct)
    if not labeled and len(distinct) == 1:
        return next(iter(distinct.values())), "inferred", 1
    return None, None, len(distinct)


def legal_description(text: str) -> str | None:
    flat = re.sub(r"[ \t]+", " ", text)
    for label in re.finditer(r"(?i)property\s+to\s+be\s+sold|legal\s+description|described\s+as\s+follows|property\s*:", flat):
        start = LEGAL_START.search(flat, label.end(), label.end() + 600)
        if start:
            end = LEGAL_END.search(flat, start.start(), start.start() + 500)
            snippet = flat[start.start():end.start() if end else start.start() + 300]
            return _clean(snippet)[:400] or None
    start = LEGAL_START.search(flat)
    if start:
        end = LEGAL_END.search(flat, start.start(), start.start() + 500)
        return _clean(flat[start.start():end.start() if end else start.start() + 300])[:400] or None
    return None


def principal(text: str) -> float | None:
    flat = re.sub(r"\s+", " ", text)
    for pattern in PRINCIPAL:
        match = pattern.search(flat)
        if match:
            digits = match.group(1)
            whole, _, cents = digits.rpartition(".") if re.search(r"\.\d{2}$", digits) else (digits, "", "")
            value = float(re.sub(r"[,.]", "", whole) + (f".{cents}" if cents else ""))
            if 1000 <= value <= 500_000_000:
                return value
    # Two-column forms: the label and its value are read apart.
    label = re.search(r"(?i)original\s+principal", text)
    if label:
        money = re.search(MONEY, text[label.end():label.end() + 600])
        if money:
            return principal(f"original principal amount of ${money.group(1)}")
    return None


def lender(text: str) -> str | None:
    flat = re.sub(r"\s+", " ", text)
    for number, pattern in enumerate(LENDER):
        # The "whose address is" and "is the current mortgagee" sentences run over lines;
        # the labeled fields are read line by line.
        match = pattern.search(flat if number in (0, 2) else text)
        if match:
            # A sentence may run into the name: keep what follows its last full stop.
            value = re.split(r"(?<=[a-z]{2})\.\s+", _clean(match.group(1)))[-1]
            value = re.split(r"(?i),?\s+(?:is|and|as)\s+(?:the\s+)?(?:mortgage\s+servicer|current|holder|trustee)", value)[0]
            value = _clean(value)
            value = re.sub(r"^(?:o|c/o)\s+", "", value)
            value = re.sub(r"(?i),?\s+(?:not\s+in\s+its\s+individual\s+capacity|not\s+individually|its\s+address\s+being|whose\s+addre?ss?\s+is)\b.*", "", value)
            value = re.sub(r"(?i)^note\s+dated\s+.{0,40}?\s+amount\s+of\s+[S$]?[\d,. ]*", "", value)
            if (len(value) >= 4 and re.match(r"[A-Z0-9]", value) and ":" not in value and not re.search(r"\b[A-Z]{2}\s+\d{5}\b|\bP\.?O\.? Box\b", value)
                    and not re.match(r"(?i)(?:mortgage|address|the\s+note|this|said|recorded|property|substitute|date|legal)\b", value)
                    # Only an organisation: a private individual lender's name is left out,
                    # and so is OCR noise that matched the sentence.
                    and ORGANISATION.search(value) and not NOT_A_LENDER.search(value)):
                return value[:200]
    return None


def parse_notice(text: str) -> dict:
    address, address_source, candidate_count = pick_address(text)
    legal = legal_description(text)
    lot = LOT.search(legal or "")
    block = BLOCK.search(legal or "")
    subdivision = SUBDIVISION.search(legal or "")
    association = HOA.search(text)
    hoa = bool(association and re.search(r"(?i)assessment", text) and not re.search(r"(?i)deed\s+of\s+trust", text))
    return {
        "street": address["street"] if address else None,
        "city": address["city"] if address else None,
        "zip_code": address["zip"] if address else None,
        "address_source": address_source,
        "address_candidates": candidate_count,
        "legal_description": legal,
        "lot": lot.group(1) if lot else None,
        "block": block.group(1) if block else None,
        "subdivision": _clean(subdivision.group(1)).upper() if subdivision else None,
        "section": subdivision.group(2) if subdivision and subdivision.group(2) else None,
        "original_principal": principal(text),
        "lender": lender(text),
        "notice_kind": "association_assessment_lien" if hoa else "deed_of_trust",
        "ocr_chars": len(text),
    }
