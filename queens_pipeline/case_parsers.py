"""Parsers for the per-case files saved by hand: WebCivil pages and NYSCEF filings.

A file can hold several sections. Pages are grouped into documents first:
  - WebCivil pages by their title ("WebCivil Supreme - Appearance Detail", "- Case Detail");
  - NYSCEF filings by the clerk's stamp on every page
    ("FILED: QUEENS COUNTY CLERK 09/16/2026 ... INDEX NO. 713725/2021 NYSCEF DOC. NO. 133").
Each document is then classified from its own text (never the file name, which is
sometimes wrong) and parsed with deterministic regexes. A value that is not in the
text is left out, never guessed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

INDEX_IN_NAME = re.compile(r"^\s*(\d{3,6})\s*[-:]\s*(\d{4})(?=[\s._]|$)")
WEBCIVIL = {
    "WebCivil Supreme - Appearance Detail": "appearances",
    "WebCivil Supreme - Case Detail": "case_detail",
}
STAMP = re.compile(r"FILED:?\s*(\w+(?:\s\w+)?)\s+COUNTY\s+CLERK\s+(\d{2}/\d{2}/\d{4})"
                   r".{0,80}?NYSCEF\s+DOC\.?\s*NO\.?\s*(\d+)", re.S)
SECTIONS = ("case_detail", "appearances", "efiled_documents", "notice_of_sale", "summons_complaint",
            "notice_of_pendency", "judgment_of_foreclosure", "other")
MONEY = r"\$\s*(\d{1,3}(?:,\s?\d{3})+(?:\.\d{2})?|\d+(?:\.\d{2})?)"


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def index_from_file_name(name: str) -> str | None:
    """'713725-2021 Notice_of_sales.pdf', '705527- 2014 summons.pdf', '710760:2021 Summons.pdf' -> index number."""
    match = INDEX_IN_NAME.match(name)
    return f"{int(match[1])}/{match[2]}" if match else None


def iso(date: str, fmt: str = "%m/%d/%Y") -> str | None:
    try:
        return datetime.strptime(date, fmt).date().isoformat()
    except ValueError:
        return None


def money(value: str) -> float:
    return float(re.sub(r"[,\s]", "", value))


@dataclass
class Document:
    section: str
    pages: list[int]                 # 0-based page numbers in the file
    text: str
    doc_number: int | None = None    # NYSCEF document number
    filed_date: str | None = None    # ISO date from the clerk's stamp


# A filing's own title comes before the documents it recites: a summons asks for a
# "judgment of foreclosure and sale", and a judgment recites the summons and complaint.
TITLES = [
    ("notice_of_sale", r"NOTICE\s*OF\s*(?:\w+\s*){0,3}SALE|WILL\s*SELL\s*AT\s*PUBLI\w*\s*AUCTION"),
    ("judgment_of_foreclosure", r"JUDGMENT\s*OF\s*FORECLOSURE\s*(?:AND|&)\s*SALE"),
    ("summons_complaint", r"SUMMONS\s*AND\s*(?:VERIFIED\s*)?(?:COMPLAINT|NOTICE)|\bSUMMONS\b"),
    ("notice_of_pendency", r"NOTICE\s*OF\s*PENDENCY"),
    ("efiled_documents", r"NYSCEF.{0,40}DOCUMENT\s*LIST|EFILED\s*DOCUMENTS"),
    ("other", r"MEMORANDUM|DECISION\s*(?:AND|&)\s*ORDER|SHORT\s*FORM\s*ORDER|ORDER\s*TO\s*SHOW\s*CAUSE"),
]


def classify(text: str) -> str:
    """The kind of a NYSCEF filing: whichever title appears first in it."""
    head = flat(text[:12000]).upper()
    # Skip the clerk's stamp, which every page starts with.
    head = re.sub(r"^FILED:.{0,140}?RECEIVED NYSCEF:\s*\d{2}/\d{2}/\d{4}", "", head)
    first = None
    for section, pattern in TITLES:
        match = re.search(pattern, head)
        if match and (first is None or match.start() < first[0]):
            first = (match.start(), section)
    if first and first[1] == "summons_complaint" and not re.search(r"COMPLAINT|SUMMONS\s*AND\s*NOTICE", head):
        return "other"
    return first[1] if first else "other"


def split_documents(pages: list[str]) -> list[Document]:
    documents: list[Document] = []
    current_key = None
    for number, page in enumerate(pages):
        text = flat(page)
        key = None
        for title, section in WEBCIVIL.items():
            if title in text:
                key = ("webcivil", section)
        stamp = STAMP.search(text[:600]) if key is None else None
        if stamp:
            key = ("nyscef", int(stamp[3]))
        if key is None:
            key = current_key or ("unstamped", 0)
        if key != current_key or not documents:
            documents.append(Document(
                section=key[1] if key[0] == "webcivil" else "",
                pages=[], text="",
                doc_number=key[1] if key[0] == "nyscef" else None,
                filed_date=iso(stamp[2]) if stamp else None))
            current_key = key
        documents[-1].pages.append(number)
        documents[-1].text += page + "\n\f\n"
    for document in documents:
        if not document.section:
            document.section = classify(document.text)
    return documents


# --- WebCivil Case Detail ----------------------------------------------------------------

def parse_case_detail(text: str) -> dict:
    def line(label: str) -> str | None:
        match = re.search(rf"^{label}:[ \t]*(.*)$", text, re.M)
        return match[1].strip() or None if match else None
    disposition = line("Disposition Date")
    return {
        "index_number": line("Index Number"),
        "cms_index": line("CMS Index Number"),
        "justice": line("Justice Name"),
        "case_status": f"Disposed {disposition}" if disposition else None,
        "caption": line("Case Name"),
    }


# --- WebCivil Appearance Detail (word positions) -----------------------------------------

APPEARANCE_COLUMNS = ["date", "time", "purpose", "fully_virtual", "court_date_type", "outcome",
                      "justice_part", "remarks", "motion_seq"]
DATE_CELL = re.compile(r"^\d{2}/\d{2}/\d{4}$")


def _column_starts(words: list[dict]) -> list[float] | None:
    """x positions where each column starts, read from the two header lines:

        Appearance  Court Date  Fully  Court Date  Outcome  Justice  Motion
        Date  Time  Purpose  VirtualType  Type  Part  Remarks  Seq

    Widths differ between cases, so every start is measured, mostly on the first line."""
    for word in words:
        if word["text"] != "Purpose":
            continue
        line = [w for w in words if abs(w["top"] - word["top"]) < 2]
        above = [w for w in words if 4 < word["top"] - w["top"] < 16]

        def x(items, test):
            found = [w["x0"] for w in items if test(w["text"])]
            return min(found) if found else None
        date, time = x(line, lambda t: t == "Date"), x(line, lambda t: t == "Time")
        virtual, outcome = x(above, lambda t: t == "Fully"), x(above, lambda t: t == "Outcome")
        part, seq = x(above, lambda t: t == "Justice"), x(above, lambda t: t == "Motion")
        remarks = x(line, lambda t: t.startswith("Remarks"))
        if None in (date, time, virtual, outcome, part, remarks):
            continue
        court_type = x([w for w in above if virtual < w["x0"] < outcome], lambda t: t == "Court")
        return [date, time, word["x0"], virtual, court_type or (virtual + outcome) / 2, outcome, part, remarks,
                seq or remarks + 100]
    return None


def _split_at_columns(words: list[dict], starts: list[float]) -> list[dict]:
    """Text from two neighbouring cells can print as one word ("Auction-ForeclosedNo",
    "-Mayersohn,"): split a word that starts well inside one column and runs into the next."""
    result = []
    for word in words:
        edge = next((x for x in starts if word["x0"] < x - 4 and word["x1"] > x + 2), None)
        chars = word.get("chars") or []
        cut = next((i for i, char in enumerate(chars) if char["x0"] >= edge - 1), None) if edge else None
        if not cut:
            result.append(word)
            continue
        left, right = chars[:cut], chars[cut:]
        result.append({**word, "text": "".join(c["text"] for c in left), "x1": left[-1]["x1"]})
        result.append({**word, "text": "".join(c["text"] for c in right), "x0": right[0]["x0"]})
    return result


def _join(lines: list[str]) -> str | None:
    text = ""
    for line in lines:
        if not text:
            text = line
        elif re.search(r"[A-Za-z]-$", text):  # "Auction-" + "Foreclosed"
            text += line
        else:
            text += " " + line
    return text.strip() or None


NAME_LINE = re.compile(r"(?:Hon\.\s)?[A-Z][A-Za-z.'\-]*(?:\s[A-Z][A-Za-z.'\-]*){0,2}")
INITIALS = re.compile(r"[A-Z]\.?(?:\s?[A-Z]\.)*")
# Words that start a part name, never a justice's name ("Centralized Motion Part").
PART_WORDS = {"Centralized", "Motion", "Motions", "Part", "Trial", "Foreclosure", "Status", "Conference",
              "Compliance", "Scheduling", "Exparte"}


def _split_justice_part(lines: list[str]) -> tuple[str | None, str | None]:
    """The 'Justice Part' column prints the justice above the part:
    'Mayersohn, Hon.' / 'Lee A.' / 'PART 22 MOTIONS', or 'Cohanim' / 'Lancman, Hon.' / 'Mojgan' / 'PART 20 MOTIONS'."""
    if not lines:
        return None, None
    if lines[0].startswith("(Master"):
        end = next((i for i, line in enumerate(lines) if "MFJ" in line), 0)
        return _join(lines[:end + 1]), _join(lines[end + 1:])
    comma = next((i for i, line in enumerate(lines[:2]) if "," in line), None)
    if comma is None:
        return None, _join(lines)
    end = comma + 1
    # A name continues with first and middle names and initials ("Lee A.", "Joseph", "N.");
    # the part starts with an upper-case line ("PART 22 MOTIONS") or a part word.
    while end < len(lines) and (INITIALS.fullmatch(lines[end]) or (
            NAME_LINE.fullmatch(lines[end]) and not lines[end].isupper()
            and not PART_WORDS & set(lines[end].replace(".", "").split()))):
        end += 1
    return _join(lines[:end]), _join(lines[end:])


def parse_appearances(pdf_pages) -> list[dict]:
    """Rows of a WebCivil Appearance Detail table. pdf_pages are pdfplumber pages of that section."""
    starts = None
    rows: list[dict] = []
    for page in pdf_pages:
        # A tight gap tolerance keeps text from neighbouring cells apart ("Auction-Foreclosed" | "No").
        words = [w for w in page.extract_words(x_tolerance=1.5, return_chars=True) if 25 < w["top"] < page.height - 30]
        starts = _column_starts(words) or starts
        if starts is None:
            continue
        header_top = next((w["top"] for w in words if w["text"] == "Purpose"), None)
        body = [w for w in words if header_top is None or w["top"] > header_top + 2]
        body = [w for w in body if w["text"] != "Close"]
        for word in sorted(_split_at_columns(body, starts), key=lambda w: (round(w["top"]), w["x0"])):
            column = max(i for i, x in enumerate(starts) if word["x0"] >= x - 3) if word["x0"] >= starts[0] - 3 else 0
            if column == 0 and DATE_CELL.match(word["text"]):
                rows.append({name: [] for name in APPEARANCE_COLUMNS})
                rows[-1]["_lines"] = {}
            if not rows:
                continue
            cells = rows[-1]["_lines"].setdefault(column, {})
            # Words on the same line of one cell join with spaces; new lines start new entries.
            line_key = (page.page_number, round(word["top"]))
            cells.setdefault(line_key, []).append(word["text"])
    result = []
    for row in rows:
        values = {}
        for column, name in enumerate(APPEARANCE_COLUMNS):
            lines = [" ".join(parts) for _, parts in sorted(row["_lines"].get(column, {}).items())]
            values[name] = lines
        justice, part = _split_justice_part(values["justice_part"])
        result.append({
            "appearance_date": iso(_join(values["date"]) or ""),
            "time": _join(values["time"]),
            "purpose": _join(values["purpose"]),
            "court_date_type": _join(values["court_date_type"]),
            "outcome": _join(values["outcome"]),
            "justice": justice,
            "part": part,
            "remarks": _join(values["remarks"]),
            "motion_seq": _join(values["motion_seq"]),
        })
    return result


# --- Addresses and block/lot -------------------------------------------------------------

def _repair_numbers(text: str) -> str:
    """OCR repairs inside numbers: 'l22nd' -> '122nd', 'll742' -> '11742', '133- 44' -> '133-44'."""
    text = re.sub(r"(?<![A-Za-z])[lI](?=[\dlI]*\d)", "1", text)
    text = re.sub(r"(?<=\d)[lI](?=\d)", "1", text)
    return re.sub(r"(\d)\s*-\s*(\d)", r"\1-\2", text)


def ordinal_case(street: str) -> str:
    return re.sub(r"(\d)(St|Nd|Rd|Th)\b", lambda m: m[1] + m[2].lower(), street)


def tidy(value: str) -> str:
    value = " ".join(value.split()).strip(" ,.;")
    return ordinal_case(value.title()) if value.isupper() else value


ADDRESS = re.compile(
    r"(?P<street>\d{1,6}(?:-\d{1,4})?\s+[^,;]{3,70}?(?:,\s*(?:Unit|Apt\.?|#)\s*[\w-]+)?)\s*,\s*"
    r"(?P<city>[A-Za-z][A-Za-z .'/]{2,60}?)\s*,?\s*(?:N\W{0,2}Y(?![A-Za-z])\.?|New\s*York)\s*,?\s*(?P<zip>1\d{4})")


def split_address(raw: str, county: str) -> dict | None:
    """'93-08 76THSTREET, WOODHAVENN,Y 11421' -> street, city, zip. The first of several a/k/a names is kept."""
    text = _repair_numbers(flat(raw))
    if county == "Queens":
        # A Queens house number whose hyphen OCR read as a space: '57 48 Van Doren Street'.
        text = re.sub(r"^(\d{2,3})\s(\d{2})(?=\s+[A-Za-z0-9])", r"\1-\2", text)
        # One printed without it: '15826 78th Avenue' is 158-26. Only before a numbered street,
        # so a Rockaway number ('171 Beach 91st Street') is left alone.
        text = re.sub(r"^(\d{2,3})(\d{2})(?=\s+\d+(?:st|nd|rd|th)\b)", r"\1-\2", text, flags=re.I)
    match = ADDRESS.match(text)
    if not match:
        return None
    street = re.split(r"\s+a/?k/?a\s+", match["street"], maxsplit=1, flags=re.I)[0]
    # A caption printed beside the address: "119-19 198th Street Plaintiff,".
    street = re.sub(r"\s+(?:Plaintiffs?|Defendants?|-?against-?)$", "", street, flags=re.I)
    city = re.split(r"\s+a/?k/?a\s+", match["city"], maxsplit=1, flags=re.I)[0]
    street = re.sub(r"(\d)(?:ST|ND|RD|TH)(STREET|AVENUE|ROAD|PLACE|DRIVE)\b",
                    lambda m: f"{m[0][:-len(m[2])]} {m[2]}", street)  # "76THSTREET" -> "76TH STREET"
    return {"property_address": tidy(street), "city": tidy(city), "zip": match["zip"]}


BLOCK_LOT = [
    re.compile(r"\bBlock\s*(?:No\.?)?\s*:?\s*([\dlI]{1,5})\s*[,;]?\s*(?:and\s+)?Lots?\s*(?:No\.?)?\s*:?\s*"
               r"([\dlI]{1,4}(?:\s*(?:,|and|&)\s*[\dlI]{1,4})*)", re.I),
    re.compile(r"tax\s*map\s*identification\s*:?\s*(\d{1,5})\s*-\s*(\d{1,4})", re.I),
    re.compile(r"PROPERTY\s*DATA\s+Borough\s+Block\s+Lot.{0,40}?QUEENS\s+(\d{1,5})\s+(\d{1,4})\b", re.I),
]
BOROUGH_CODE = {"Manhattan": 1, "New York": 1, "Bronx": 2, "Kings": 3, "Queens": 4, "Richmond": 5}


def block_lot(text: str, county: str) -> str | None:
    """'4-10497-29' (borough code, block, lot); several lots: '4-12073-429/430'."""
    body = flat(text)
    for pattern in BLOCK_LOT:
        if match := pattern.search(body):
            block = _repair_numbers(match[1])
            lots = [_repair_numbers(lot) for lot in re.split(r"\s*(?:,|and|&)\s*", match[2])]
            code = BOROUGH_CODE.get(county)
            prefix = f"{code}-" if code else ""
            return f"{prefix}{int(block)}-{'/'.join(str(int(lot)) for lot in lots)}"
    return None


# --- Notice of Sale ----------------------------------------------------------------------

def parse_notice_of_sale(text: str, county: str) -> dict:
    body = flat(text)
    values: dict = {}
    premises = re.search(r"premises\s*known\s*as\s*:?\s*(.{10,200})", body, re.I)
    if premises and (address := split_address(premises[1], county)):
        values.update(address)
    values["borough_block_lot"] = block_lot(body, county)
    # The referee signs: "Helmut Borchert, Esq., Referee" / "Robert Howe, Referee".
    # "Dana L. Jenkins, Esq. - Referee", "MARTHA TAYLOR, ESQ., Referee".
    # "Gerald Chiariello, II, Esq. - Referee" keeps its suffix.
    referees = re.findall(r"([A-Z][A-Za-z.'\-]*(?:\s+[A-Z][A-Za-z.'\-]*){1,3}(?:,\s*(?:Jr|Sr|II|III|IV)\.?)?)"
                          r"\s*,\s*(?:(?i:Esq)\.?\s*)?[,\-–]?\s*"
                          r"(?i:Referee)\b", body)
    if referees:
        # OCR doubles a capital ("JJais") or drops the space before a middle initial ("NedaM.").
        name = re.sub(r"\b([A-Z])\1(?=[a-z])", r"\1", tidy(referees[-1]))
        values["referee_name"] = re.sub(r"([a-z])([A-Z]\.)", r"\1 \2", name)
    # "Approximate amount of judgment is $X" / "the approximate amount of the current (OCR: cunent)
    # Judgment lien is $X". "Approximate amount of lien $X" names no judgment, so it is kept apart.
    judgment = re.search(r"amount\s+of\s+(?:the\s+)?(?:cu\w{1,3}nt\s+)?judgment(?:\s+lien)?\s*(?:is|of|:)?\s*" + MONEY,
                         body, re.I)
    lien = None if judgment else re.search(r"approximate\s+amount\s+of\s+(?:the\s+)?lien\s*(?:is|of|:)?\s*" + MONEY,
                                           body, re.I)
    values["approximate_judgment"] = money(judgment[1]) if judgment else None
    values["approximate_lien_amount"] = money(lien[1]) if lien else None
    sale = re.search(r"(?:will\s+sell|publi\w*\s+a?uction).{0,220}?\bon\s+((?:January|February|March|April|May|June|"
                     r"July|August|September|October|November|December)\s+\d{1,2},?\s+20\d{2})", body, re.I)
    values["notice_auction_date"] = iso(re.sub(r",?\s+", " ", sale[1]), "%B %d %Y") if sale else None
    return {key: value for key, value in values.items() if value}


# --- Summons and Complaint ---------------------------------------------------------------

PREMISES = [
    re.compile(r"Mortgaged?\s+Premises\s*:\s*(.{10,200})", re.I),
    re.compile(r"(?:premises|property)\s*(?:is\s+|are\s+)?(?:commonly\s+)?(?:known\s*as|located\s+at)\s*:?\s*(.{10,200})", re.I),
    re.compile(r"(?:covering|encumbering|secured)\s+(?:the\s+)?(?:real\s+)?(?:premises|property)\s+(?:known\s+as\s+)?(.{10,200})", re.I),
]
PRINCIPAL = [
    re.compile(r"(?:ENTIRE\s*)?Principal\s*balance\s*:\s*" + MONEY, re.I),
    re.compile(r"(?:now|presently)\s*(?:an\s+|justly\s+)?(?:due\s+and\s+owing|due)\b[^$]{0,220}?principal\s+(?:sum|balance|amount)"
               r"[^$]{0,40}?" + MONEY, re.I),
    re.compile(r"(?:unpaid|outstanding)\s+principal\s+(?:balance|sum|amount)[^$]{0,80}?" + MONEY, re.I),
]
NAME = r"([A-Z][A-Za-z0-9&.,'’\- ]{2,110}?)"
MORTGAGEE = [
    re.compile(r"(?:executed|acknowledged)(?:,?\s*(?:and\s+)?(?:acknowledged|executed))?,?\s*(?:and\s+)?delivered\s+"
               r"(?:to\s+)?" + NAME + r",?\s+(?:a|an)\s+(?:certain\s+)?(?:adjustable\s+rate\s+)?(?:note|bond|mortgage)\b",
               re.I),
    re.compile(r"note\s*and\s*mortgage\s*with\s+" + NAME + r"\s*(?:\(|,?\s*in\s+the\s+amount)", re.I),
    re.compile(r"with\s+the\s+original\s+lender,?\s+" + NAME + r"\s*\(", re.I),
]
NOT_A_LENDER = re.compile(r"plaintiff|assignor|stated lender|obligee|following|the mortgagee", re.I)


def parse_summons(document: Document, county: str) -> dict:
    # The complaint's facts come early; the mortgage and note exhibits after them repeat boilerplate.
    body = flat(document.text)[:60000]
    values: dict = {}
    for pattern in PREMISES:
        for match in pattern.finditer(body):
            if address := split_address(match[1], county):
                values.update(address)
                break
        if "property_address" in values:
            break
    values["borough_block_lot"] = block_lot(body, county)
    for pattern in PRINCIPAL:
        if match := pattern.search(body):
            values["unpaid_principal"] = money(match[1])
            break
    for pattern in MORTGAGEE:
        for match in pattern.finditer(body):
            name = match[1].strip(" ,")
            if not NOT_A_LENDER.search(name) and len(name.split()) >= 2:
                values["original_mortgagee"] = name
                break
        if "original_mortgagee" in values:
            break
    head = flat(document.text[:8000]).upper()
    title = ("Summons and Notice" if re.search(r"SUMMONS\s*AND\s*NOTICE", head)
             else "Supplemental Summons and Amended Complaint" if "SUPPLEMENTAL SUMMONS" in head
             else "Amended Summons and Complaint" if re.search(r"AMENDED\s+(?:VERIFIED\s+)?(?:SUMMONS|COMPLAINT)", head)
             else "Summons and Complaint")
    values["document_title"] = title
    return {key: value for key, value in values.items() if value is not None}


def parse_notice_of_pendency(document: Document, county: str) -> dict:
    body = flat(document.text)
    values: dict = {"borough_block_lot": block_lot(body, county)}
    for pattern in PREMISES:
        if (match := pattern.search(body)) and (address := split_address(match[1], county)):
            values.update(address)
            break
    return {key: value for key, value in values.items() if value is not None}
