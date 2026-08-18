"""Fixed-width readers for New Jersey MOD-IV and SR-1A public files."""
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path
from typing import Iterator

def field(line: str, start: int, end: int) -> str:
    return line[start - 1:end].strip()

def normalize_component(value: str) -> str:
    compact = "".join(value.upper().split())
    return compact.lstrip("0") or ("0" if compact else "")

def number(value: str, scale: int = 0) -> Decimal | None:
    value = value.strip().replace(",", "")
    if not value or not value.lstrip("+-").isdigit(): return None
    try: return Decimal(value).scaleb(-scale)
    except InvalidOperation: return None

def integer(value: str) -> int | None:
    value = number(value)
    return int(value) if value is not None else None

def state_date(value: str) -> date | None:
    value = value.strip()
    if len(value) != 6 or not value.isdigit() or value == "000000": return None
    short_year, month, day = int(value[:2]), int(value[2:4]), int(value[4:])
    year = 2000 + short_year if short_year <= 69 else 1900 + short_year
    try: return date(year, month, day)
    except ValueError: return None

@dataclass(frozen=True)
class ModivRecord:
    source_year: int; municipality_code: str; block: str; lot: str; qualifier: str
    record_id: str; property_class: str; property_location: str
    building_description: str; land_description: str; acreage: Decimal | None
    zoning: str; deed_date: date | None; sale_price: Decimal | None
    sale_nonusable_code: str; building_class: str; year_built: int | None
    land_assessed: Decimal | None; improvement_assessed: Decimal | None
    total_assessed: Decimal | None; census_tract: str; census_block: str
    property_use_code: str; annual_property_tax: Decimal | None
    source_file: str; source_line_number: int; source_hash: str

@dataclass(frozen=True)
class Sr1aRecord:
    source_year: int; county_code: str; district_code: str; municipality_code: str
    block: str; lot: str; property_location: str; deed_date: date | None
    recorded_date: date | None; reported_price: Decimal | None
    verified_price: Decimal | None; land_assessed: Decimal | None
    improvement_assessed: Decimal | None; total_assessed: Decimal | None
    assessment_year: int | None; property_class: str; qualification_codes: str
    year_built: int | None; living_space: int | None; source_file: str
    source_line_number: int; source_hash: str

def parse_modiv(line: str, source_year: int, source_file: str, line_number: int) -> ModivRecord:
    raw = line.rstrip("\r\n")
    if len(raw) < 700: raise ValueError(f"MOD-IV line {line_number} has {len(raw)} characters; expected 700")
    return ModivRecord(
        source_year, field(raw,1,4), normalize_component(field(raw,5,13)),
        normalize_component(field(raw,14,22)), normalize_component(field(raw,23,33)),
        field(raw,34,35), field(raw,56,58), field(raw,59,83), field(raw,84,98),
        field(raw,99,118), number(field(raw,119,127),4), field(raw,168,171),
        state_date(field(raw,307,312)), number(field(raw,313,321)), field(raw,331,332),
        field(raw,411,415), integer(field(raw,416,419)), number(field(raw,421,429)),
        number(field(raw,430,438)), number(field(raw,439,447)), field(raw,551,555),
        field(raw,556,559), field(raw,560,562), number(field(raw,601,612),2),
        source_file, line_number, sha256(raw.encode("latin-1", errors="replace")).hexdigest())

def parse_sr1a(line: str, source_year: int, source_file: str, line_number: int) -> Sr1aRecord:
    raw = line.rstrip("\r\n")
    if len(raw) < 663: raise ValueError(f"SR-1A line {line_number} has {len(raw)} characters; expected 663")
    county, district = field(raw,1,2), field(raw,3,4)
    return Sr1aRecord(
        source_year, county, district, county+district,
        normalize_component(field(raw,351,355)+field(raw,356,359)),
        normalize_component(field(raw,360,364)+field(raw,365,368)), field(raw,298,322),
        state_date(field(raw,339,344)), state_date(field(raw,345,350)),
        number(field(raw,38,46)), number(field(raw,47,55)), number(field(raw,56,64)),
        number(field(raw,65,73)), number(field(raw,74,82)), integer(field(raw,625,626)),
        field(raw,627,629), field(raw,620,624), integer(field(raw,653,656)),
        integer(field(raw,657,663)), source_file, line_number,
        sha256(raw.encode("latin-1", errors="replace")).hexdigest())

def records(path: Path, parser, source_year: int) -> Iterator[dict]:
    with path.open(encoding="latin-1") as handle:
        for line_number, line in enumerate(handle, 1):
            yield asdict(parser(line, source_year, str(path), line_number))
