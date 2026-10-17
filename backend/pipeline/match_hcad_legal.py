"""Find street addresses for Harris County trustee notices that give only a legal description.

Many Notices of Trustee's Sale describe the property only as "LOT 23, BLOCK 1, OF
CYPRESS GREEN, SEC. 1, A SUBDIVISION IN HARRIS COUNTY, TEXAS". The Harris Central
Appraisal District publishes every parcel's legal description with its site address
(PDATA, free: download.hcad.org/data/CAMA/<year>/Real_acct_owner.zip). This module
builds a small index from that file's real_acct.txt, keeping only the account number,
site address, property class, legal description and market value (never the owner or
mailing fields), and matches a notice to a parcel by lot, block, subdivision and section.
A match is used only when exactly one parcel fits; metes-and-bounds tracts and notices
without a lot are left unmatched.

    python -m pipeline.match_hcad_legal --build            # download PDATA and write the index
    python -m pipeline.match_hcad_legal                    # report matches for without_address.json

load_tx_trustee_sales applies the matches when the index exists.
"""
import argparse
import csv
import difflib
import io
import json
import re
import zipfile
from collections import defaultdict
from datetime import date
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2] / ".local" / "hcad"
PDATA_URL = "https://download.hcad.org/data/CAMA/{year}/Real_acct_owner.zip"
INDEX_COLUMNS = ["acct", "site_addr_1", "site_addr_2", "site_addr_3", "state_class",
                 "lgl_1", "lgl_2", "lgl_3", "lgl_4", "tot_mkt_val"]
SOURCE = "hcad_legal_description"

WORD_NUMBERS = {word: number for number, word in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen"
    " seventeen eighteen nineteen twenty".split())}
ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10,
         "XI": 11, "XII": 12, "XIII": 13, "XIV": 14, "XV": 15, "XVI": 16, "XVII": 17, "XVIII": 18, "XIX": 19, "XX": 20}
# Words HCAD abbreviates or drops; both sides are reduced to the same form.
ABBREVIATIONS = {"ESTATES": "EST", "ESTS": "EST", "VILLAGE": "VLG", "VILLAGES": "VLGS", "HEIGHTS": "HTS",
                 "TERRACE": "TER", "PLACE": "PL", "PARK": "PK", "MEADOWS": "MDWS", "MEADOW": "MDW", "LAKES": "LKS",
                 "LAKE": "LK", "SPRINGS": "SPGS", "SPRING": "SPG", "GARDENS": "GDNS", "GARDEN": "GDN", "FOREST": "FOR",
                 "CREEK": "CRK", "RANCH": "RNCH", "TRAILS": "TRLS", "TRAIL": "TRL", "POINTE": "PT", "POINT": "PT",
                 "CROSSING": "XING", "MOUNT": "MT", "SAINT": "ST", "NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W",
                 "PARTIAL": "", "REPLAT": "R/P", "REPLATS": "R/P", "AMENDING": "AMEND", "AMENDED": "AMEND"}
DROP = {"OF", "THE", "A", "AN", "ADDITION", "ADD", "SUBDIVISION", "SUBD", "SUB", "NO", "AND", "&", "AMEND", "R/P", "U/R"}


def number(token: str | None) -> str | None:
    """'23', '(23)', 'TWENTY-THREE (23)', 'E', '"E"' -> a lot or block key."""
    if not token:
        return None
    token = token.strip().strip('"“”\'()., ').upper()
    if token.isdigit():
        return str(int(token))
    if re.fullmatch(r"\d+[A-Z]|[A-Z]{1,2}|[A-Z]-?\d+|\d+-[A-Z]", token):
        return token.replace("-", "")
    return None


def section(text: str) -> str | None:
    match = re.search(r"(?i)\b(?:SEC(?:TION)?|SECT)\.?\s*(?:NO\.?\s*)?([0-9]+|[IVX]+\b|[A-Z]+(?:\s*\(\d+\))?)", text)
    if not match:
        return None
    value = match.group(1).upper()
    digits = re.search(r"\((\d+)\)", value)
    if digits:
        return str(int(digits.group(1)))
    if value.isdigit():
        return str(int(value))
    if value in ROMAN:
        return str(ROMAN[value])
    return str(WORD_NUMBERS[value.lower()]) if value.lower() in WORD_NUMBERS else None


def name_key(text: str) -> str:
    """Subdivision name without section, punctuation and the words HCAD drops."""
    text = re.sub(r"(?i)\b(?:SEC(?:TION)?|SECT)\.?\s*(?:NO\.?\s*)?\S+.*$", "", text.upper())
    tokens = re.sub(r"[^A-Z0-9&/ ]+", " ", text).split()
    tokens = [ABBREVIATIONS.get(token, token) for token in tokens]
    return " ".join(token for token in tokens if token and token not in DROP)


LOT_RE = re.compile(r"(?i)\bLOTS?\s+(?:[A-Z][A-Z\-]*\s+)?\(?\s*([0-9]+[A-Z]?|\"?[A-Z]\"?)\s*\)?")
BLOCK_RE = re.compile(r"(?i)\bBLOCK\s+(?:[A-Z][A-Z\-]*\s+)?(\(\s*[0-9A-Z]+\s*\)|[0-9]+[A-Z]?|\"[A-Z0-9]+\"|[A-Z]\b)")
SUBDIVISION_RE = re.compile(r"(?i)\bBLOCK\s+[^,]*?\)?\s*,?\s*(?:IN\s+|OF\s+)+[.,]?\s*(.+?)(?:,?\s+(?:A|AN)\s+(?:SUBDIVISION|ADDITION|"
                            r"PARTIAL\s+REPLAT|REPLAT)|,?\s+(?:IN|OF)\s+HARRIS\s+COUNTY|,?\s+ACCORDING\s+TO|,?\s+(?:AS\s+)?RECORDED|$)")


def notice_key(legal: str) -> dict | None:
    """Lot, block, subdivision name and section from a notice's legal description."""
    legal = re.sub(r"\s+", " ", legal or "")
    if re.search(r"(?i)\bunit\b|condominium|metes\s+and\s+bounds|\d[\d.,]*\s+acres?\b|\babstract\b|\bsurvey\b", legal[:200]):
        return None
    lot, block = LOT_RE.search(legal), BLOCK_RE.search(legal)
    subdivision = SUBDIVISION_RE.search(legal)
    if not (lot and block and subdivision):
        return None
    lot_value = number(lot.group(1))
    block_value = number(re.sub(r"[()\s]", "", block.group(1)))
    name = subdivision.group(1)
    if not (lot_value and block_value and name_key(name)):
        return None
    return {"lot": lot_value, "block": block_value, "name": name_key(name), "section": section(name)}


HCAD_LOT_BLOCK = re.compile(r"^(?:LTS?|LOTS?)\s+([0-9]+[A-Z]?|[A-Z])\b.*?\bBLK\s+([0-9A-Z\-]+)\b")


def hcad_key(row: dict) -> tuple[str, str] | None:
    match = HCAD_LOT_BLOCK.match(row["lgl_1"])
    if not match:
        return None
    return number(match.group(1)), number(match.group(2))


def load_index(path: Path) -> dict[tuple[str, str], list[dict]]:
    index = defaultdict(list)
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            key = hcad_key(row)
            if key and all(key) and row["site_addr_1"] and not row["site_addr_1"].startswith("0 "):
                index[key].append(row)
    return index


def same_subdivision(notice: dict, row: dict) -> bool:
    legal = " ".join(row[f"lgl_{n}"] for n in (2, 3, 4) if row[f"lgl_{n}"])
    if notice["section"] and section(legal) not in (None, notice["section"]):
        return False
    if notice["section"] and section(legal) is None and re.search(r"(?i)\bSEC\b", legal):
        return False
    name = name_key(legal)
    # A section on the notice that HCAD does not show: only an exact name will do.
    if notice["section"] and section(legal) is None:
        return name == notice["name"]
    return similar_names(name, notice["name"])


def similar_names(hcad: str, notice: str) -> bool:
    """Equal, or word for word with OCR slips allowed only in words of five letters or more
    (LAKEWOOI = LAKEWOOD), so LINDALE PL never matches LINDALE PK."""
    if not hcad or not notice:
        return False
    if hcad == notice:
        return True
    ours, theirs = notice.split(), hcad.split()
    return len(ours) == len(theirs) and all(
        a == b or (min(len(a), len(b)) >= 5 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.85)
        for a, b in zip(ours, theirs))


def match(notice: dict, index: dict) -> dict | None:
    key = notice_key(notice.get("legal_description") or "")
    if not key:
        return None
    candidates = [row for row in index.get((key["lot"], key["block"]), []) if same_subdivision(key, row)]
    if len(candidates) != 1:
        return None
    row = candidates[0]
    return {"street": row["site_addr_1"].title(), "city": row["site_addr_2"].title() or None,
            "zip_code": (row["site_addr_3"] or "")[:5] or None, "address_source": SOURCE,
            "hcad_account": row["acct"], "hcad_legal": " ".join(row[f"lgl_{n}"] for n in (1, 2, 3, 4) if row[f"lgl_{n}"])}


def latest_index() -> Path | None:
    indexes = sorted(ROOT.glob("*/legal_index.tsv"))
    return indexes[-1] if indexes else None


def build(year: int) -> Path:
    """Download PDATA's Real_acct_owner.zip and keep only the index columns of real_acct.txt."""
    folder = ROOT / str(year)
    folder.mkdir(parents=True, exist_ok=True)
    archive = folder / "Real_acct_owner.zip"
    if not archive.exists():
        with httpx.stream("GET", PDATA_URL.format(year=year), timeout=600, follow_redirects=True) as response:
            response.raise_for_status()
            with archive.open("wb") as handle:
                for chunk in response.iter_bytes():
                    handle.write(chunk)
    csv.field_size_limit(10**9)
    output = folder / "legal_index.tsv"
    with zipfile.ZipFile(archive) as bundle, bundle.open("real_acct.txt") as raw, \
            output.open("w", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(io.TextIOWrapper(raw, encoding="latin-1", newline=""), delimiter="\t",
                                quoting=csv.QUOTE_NONE)
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(INDEX_COLUMNS)
        for row in reader:
            writer.writerow([(row.get(column) or "").strip() for column in INDEX_COLUMNS])
    return output


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--build", action="store_true", help="download PDATA and write the index")
    parser.add_argument("--year", type=int, default=date.today().year)
    parser.add_argument("--notices", type=Path, default=Path(__file__).resolve().parents[2] / ".local"
                        / "harris-trustee-notices" / "without_address.json")
    args = parser.parse_args(argv)
    if args.build:
        print(build(args.year))
        return 0
    path = latest_index()
    if not path:
        parser.error("no HCAD index yet: run with --build first")
    index = load_index(path)
    notices = json.loads(args.notices.read_text())
    keyed = [notice for notice in notices if notice_key(notice.get("legal_description") or "")]
    matched = [(notice["doc_id"], found) for notice in notices if (found := match(notice, index))]
    print(json.dumps({"index": str(path), "notices": len(notices), "lot_block_subdivision": len(keyed),
                      "matched": len(matched)}, indent=2))
    for doc_id, found in matched[:15]:
        print(doc_id, "|", found["street"], found["city"], found["zip_code"], "|", found["hcad_legal"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
