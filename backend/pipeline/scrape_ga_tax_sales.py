"""Georgia county tax sales (Fulton sheriff's tax/levy sale, Cobb tax commissioner's sale).

Georgia counties sell property for unpaid taxes on the first Tuesday of the month at the
courthouse, and post the list a few weeks before:

  Fulton  the Sheriff's Office tax-sales page links each sale's list (PDF, re-posted as it
          changes): sheriff's sale number, tax parcel ID and situs street, no names or bids.
  Cobb    the Tax Commissioner's tax-sale page links the next sale's list (PDF): owner,
          parcel, property address, starting bid and zoning. The owner column is not read.

Both PDFs are scans, so they are read with macOS Vision OCR with line positions
(pipeline/ocr_pdf_macos_boxes.swift) and rows are rebuilt from the lines' heights; this
runs on the operator's Mac, like the Harris and Fort Bend collectors. Each row's parcel ID
is looked up in the county's public parcel layer (only the ID, situs address and shape are
requested, never owner fields), which gives the official address and the map position; the
Census geocoder then gives the city and ZIP for that position. Rows whose parcel ID does
not match a parcel are reported and not kept.

PDFs, OCR output and lookups are cached in .local/ga-tax-sales/.

    python -m pipeline.scrape_ga_tax_sales [--counties Fulton Cobb]
    python -m pipeline.load_ga_tax_sales
"""
import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urljoin

from pipeline.scrape_harris_trustee_notices import first_tuesday
from pipeline.scraping.config import ScrapingSettings
from pipeline.scraping.http import PoliteClient

OUTPUT = Path("data/sheriff_sales/ga_tax_sales.json")
CACHE = Path(__file__).resolve().parents[2] / ".local" / "ga-tax-sales"
PARSER_VERSION = "ga_tax_sale_lists_v1"
CENSUS_REVERSE = "https://geocoding.geo.census.gov/geocoder/geographies/coordinates"
CENSUS_ADDRESS = "https://geocoding.geo.census.gov/geocoder/locations/address"
MONTHS = {name: number for number, name in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], start=1)}


@dataclass(frozen=True)
class County:
    name: str
    page: str
    link: re.Pattern  # the sale-list PDFs on the page
    columns: dict  # field -> (min x, max x) of the line's left edge, as a fraction of the page width
    parcel: re.Pattern  # a parcel ID as printed
    layer: str  # ArcGIS parcel layer query URL
    id_field: str
    address_field: str


def fulton_id(printed: str) -> str | None:
    """'06-0356-0004-007-8' -> '06 035600040078'; '13-0127-LL-018-4' -> '13 0127  LL0184' (fixed width)."""
    parts = re.sub(r"\s+", "", printed).split("-")
    if len(parts) != 5:
        return None
    district, book, block, lot, check = parts
    return f"{district:<3}{book}{block:>4}{lot}{check}"


def cobb_id(printed: str) -> str | None:
    """'16-0011-0-155-0' -> '16001101550'."""
    digits = re.sub(r"\D", "", printed)
    return digits if len(digits) == 11 else None


COUNTIES = {
    "Fulton": County(
        "Fulton", "https://fultoncountyga.gov/inside-fulton-county/fulton-county-departments/sheriff/tax-sales",
        re.compile(r'href=\s*"([^"]*(?:Sale-List|Levy-Sale)[^"]*?\.pdf)(?:\?[^"]*)?"', re.I),
        {"sale_number": (0.10, 0.30), "parcel": (0.30, 0.50), "street": (0.50, 0.90)},
        re.compile(r"^[0-9A-Z+]{2,3}F?\s*-\s*[0-9A-Z]{4}\s*-\s*[0-9A-Z]{2,4}\s*-\s*\d{3}\s*-\s*\d$"),
        "https://gismaps.fultoncountyga.gov/arcgispub/rest/services/OpenData/Tax_Parcels/MapServer/0/query",
        "ParcelID", "Address"),
    "Cobb": County(
        "Cobb", "https://www.cobbtax.gov/property/tax_sale/index.php",
        re.compile(r'href=\s*"([^"]*Tax Sale List[^"]*?\.pdf)(?:\?[^"]*)?"', re.I),
        {"parcel": (0.20, 0.33), "street": (0.33, 0.80), "starting_bid": (0.80, 0.95)},
        re.compile(r"^\d{2}-\d{4}-\d-\d{3}-\d$"),
        "https://gis.cobbcounty.org/gisserver/rest/services/cobbpublic/Parcels/MapServer/3/query",
        "PIN", "SITUS_ADDR"),
}
LAYER_ID = {"Fulton": fulton_id, "Cobb": cobb_id}


def ocr_boxes(pdf: Path) -> list[tuple[int, float, float, float, str]]:
    """(page, x, y, height, text) per recognized line, from macOS Vision (cached next to the PDF)."""
    cached = pdf.with_suffix(".boxes.tsv")
    if not cached.exists() or cached.stat().st_mtime < pdf.stat().st_mtime:
        script = Path(__file__).with_name("ocr_pdf_macos_boxes.swift")
        executable = CACHE / "ocr_pdf_macos_boxes"
        environment = os.environ.copy()
        module_cache = (CACHE / "swift-module-cache").resolve()
        module_cache.mkdir(parents=True, exist_ok=True)
        environment["CLANG_MODULE_CACHE_PATH"] = environment["SWIFT_MODULE_CACHE_PATH"] = str(module_cache)
        if not executable.exists() or executable.stat().st_mtime < script.stat().st_mtime:
            subprocess.run(["swiftc", "-O", str(script), "-o", str(executable)], capture_output=True, text=True,
                           timeout=300, check=True, env=environment)
        result = subprocess.run([str(executable), str(pdf)], capture_output=True, text=True, timeout=600,
                                check=True, env=environment)
        cached.write_text(result.stdout)
    boxes = []
    for line in cached.read_text().splitlines():
        page, x, y, _width, height, text = line.split("\t", 5)
        boxes.append((int(page), float(x), float(y), float(height), text.strip()))
    return boxes


def rows_from(boxes: list[tuple[int, float, float, float, str]], county: County) -> list[dict]:
    """One row per parcel-ID line, with the other columns' lines at the same height on that page."""
    rows = []
    for page, x, y, height, text in boxes:
        low, high = county.columns["parcel"]
        if not (low <= x < high and county.parcel.match(text)):
            continue
        row = {"page": page, "parcel_printed": re.sub(r"\s+", "", text)}
        for field, (low, high) in county.columns.items():
            if field == "parcel":
                continue
            same_line = [(other_x, other_text) for other_page, other_x, other_y, other_height, other_text
                         in boxes if other_page == page and low <= other_x < high
                         and abs(other_y - y) < max(height, other_height) * 0.6]
            row[field] = " ".join(text for _, text in sorted(same_line)) or None  # pieces left to right
        rows.append(row)
    return rows


def sale_date_of(boxes: list[tuple[int, float, float, float, str]]) -> date | None:
    """The sale day from the list's heading: "NOVEMBER 3, 2026, SHERIFF'S TAX / LEVY SALE" or
    "TAX SALE STARTING BIDS NOV-2026" (the first Tuesday of that month). Only lines that name the
    sale count: Cobb's list also prints the date it was run ("OCT 20, 2026")."""
    for _, _, _, _, text in boxes:
        if "SALE" not in text.upper():
            continue
        full = re.search(r"\b([A-Z]{3,9})\s+(\d{1,2}),\s*(20\d\d)\b", text.upper())
        if full and full.group(1)[:3] in MONTHS:
            return date(int(full.group(3)), MONTHS[full.group(1)[:3]], int(full.group(2)))
        month = re.search(r"\b([A-Z]{3})-(20\d\d)\b", text.upper())
        if month and month.group(1) in MONTHS:
            return first_tuesday(int(month.group(2)), MONTHS[month.group(1)])
    return None


def posting_rank(url: str) -> int:
    """Fulton re-posts a sale's list ("1st Posting", "2nd Posting"); the latest wins."""
    match = re.search(r"(\d)(?:st|nd|rd|th)-+(?:Website-+)?Posting", unquote(url), re.I)
    return int(match.group(1)) if match else 0


def layer_lookup(client: PoliteClient, county: County, ids: list[str]) -> dict[str, dict]:
    """Situs address and centroid per parcel-layer ID (no owner fields are requested)."""
    found = {}
    for start in range(0, len(ids), 50):
        batch = ids[start:start + 50]
        response = client.post(county.layer, data={
            "where": f"{county.id_field} IN ({','.join(repr(value) for value in batch)})",
            "outFields": f"{county.id_field},{county.address_field}", "returnGeometry": "true",
            "outSR": "4326", "f": "json"})
        response.raise_for_status()
        for feature in response.json().get("features") or []:
            ring = (feature.get("geometry") or {}).get("rings", [[]])[0]
            if not ring:
                continue
            found[feature["attributes"][county.id_field]] = {
                "street": " ".join((feature["attributes"].get(county.address_field) or "").split()) or None,
                "latitude": sum(point[1] for point in ring) / len(ring),
                "longitude": sum(point[0] for point in ring) / len(ring)}
    return found


def house_number(street: str | None) -> str | None:
    match = re.match(r"\s*(\d+)\b", street or "")
    return match.group(1) if match else None


def address_lookup(client: PoliteClient, county: County, street: str | None) -> dict | None:
    """The one parcel whose situs address is the listed street (house number and street words), or None."""
    number, words = house_number(street), re.findall(r"[A-Z0-9]+", (street or "").upper())
    if not number or len(words) < 2:
        return None
    pattern = "%".join(words)
    response = client.post(county.layer, data={
        "where": f"{county.address_field} LIKE '{number} %{pattern[len(number):].strip('%')}%'",
        "outFields": f"{county.id_field},{county.address_field}", "returnGeometry": "true", "outSR": "4326",
        "f": "json"})
    response.raise_for_status()
    features = response.json().get("features") or []
    if len(features) != 1 or not (features[0].get("geometry") or {}).get("rings"):
        return None
    ring = features[0]["geometry"]["rings"][0]
    return {"street": " ".join((features[0]["attributes"].get(county.address_field) or "").split()) or None,
            "latitude": sum(point[1] for point in ring) / len(ring),
            "longitude": sum(point[0] for point in ring) / len(ring), "matched_by": "address",
            "layer_id": features[0]["attributes"][county.id_field]}


def place_of(client: PoliteClient, street: str, latitude: float, longitude: float) -> tuple[str | None, str | None]:
    """(city, ZIP): the ZIP's tabulation area and the incorporated place at the parcel, or the
    postal city the Census geocoder gives for the street and ZIP when the parcel is unincorporated."""
    cached = CACHE / "places" / f"{latitude:.5f}_{longitude:.5f}.json"
    if cached.exists():
        return tuple(json.loads(cached.read_text()))
    response = client.get(CENSUS_REVERSE, params={
        "x": longitude, "y": latitude, "benchmark": "Public_AR_Current", "vintage": "Current_Current",
        "layers": "Incorporated Places,2020 Census ZIP Code Tabulation Areas", "format": "json"})
    response.raise_for_status()
    geographies = response.json()["result"]["geographies"]
    zctas = geographies.get("2020 Census ZIP Code Tabulation Areas") or []
    places = geographies.get("Incorporated Places") or []
    zip_code = zctas[0]["ZCTA5"] if zctas else None
    city = re.sub(r"\s+(city|town|village)$", "", places[0]["NAME"]) if places else None
    if city is None and zip_code and street:
        found = client.get(CENSUS_ADDRESS, params={"street": street, "state": "GA", "zip": zip_code,
                                                   "benchmark": "Public_AR_Current", "format": "json"})
        found.raise_for_status()
        matches = found.json()["result"]["addressMatches"]
        if len(matches) == 1:
            city = (matches[0]["addressComponents"].get("city") or "").title() or None
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps([city, zip_code]))
    return city, zip_code


def money_text(value: str | None) -> float | None:
    match = re.search(r"\d[\d,]*\.\d{2}", value or "")
    return float(match.group(0).replace(",", "")) if match else None


def collect(client: PoliteClient, county: County, today: date) -> tuple[list[dict], list[str]]:
    page = client.get(county.page)
    page.raise_for_status()
    base = re.search(r'<base\s+href="([^"]+)"', page.text, re.I)
    base_url = urljoin(str(page.url), base.group(1)) if base else str(page.url)
    links = sorted({urljoin(base_url, link.replace(" ", "%20")) for link in county.link.findall(page.text)})
    lists: dict[date, tuple[int, str, list]] = {}
    for url in links:
        pdf = CACHE / county.name.lower() / unquote(url.rsplit("/", 1)[-1])
        if not pdf.exists():
            response = client.get(url)
            response.raise_for_status()
            pdf.parent.mkdir(parents=True, exist_ok=True)
            pdf.write_bytes(response.content)
        boxes = ocr_boxes(pdf)
        sale_day = sale_date_of(boxes)
        if sale_day is None or sale_day < today:
            continue
        if sale_day not in lists or posting_rank(url) >= lists[sale_day][0]:
            lists[sale_day] = (posting_rank(url), url, boxes)
    parcels, unmatched = [], []
    for sale_day, (_, url, boxes) in sorted(lists.items()):
        rows = rows_from(boxes, county)
        ids = {row["parcel_printed"]: LAYER_ID[county.name](row["parcel_printed"]) for row in rows}
        places = layer_lookup(client, county, sorted({value for value in ids.values() if value}))
        for row in rows:
            layer_id = ids[row["parcel_printed"]]
            place = places.get(layer_id) if layer_id else None
            # An OCR slip in the ID can name another real parcel: its house number must be the listed one.
            listed, found = house_number(row.get("street")), house_number(place and place["street"])
            if place and listed and found and listed != found:
                place = None
            if not place:
                place = address_lookup(client, county, row.get("street"))
            if not place:
                unmatched.append(f"{county.name} {row['parcel_printed']} ({row.get('street') or 'no address'})")
                continue
            city, zip_code = place_of(client, place["street"], place["latitude"], place["longitude"]) \
                if place["street"] else (None, None)
            parcels.append({
                "county": county.name, "sale_date": sale_day.isoformat(), "list_url": url,
                # A row matched by address keeps the parcel layer's ID, not the misread one.
                "parcel": place.get("layer_id") or row["parcel_printed"], "parcel_as_listed": row["parcel_printed"],
                "sale_number": row.get("sale_number"),
                "street": place["street"], "street_as_listed": row.get("street"), "city": city, "zip_code": zip_code,
                "matched_by": place.get("matched_by", "parcel_id"),
                "starting_bid": money_text(row.get("starting_bid")),
                "latitude": place["latitude"], "longitude": place["longitude"]})
    return parcels, unmatched


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--counties", nargs="+", choices=sorted(COUNTIES), default=sorted(COUNTIES))
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    if sys.platform != "darwin":
        parser.error("The sale lists are scans read with macOS Vision OCR: run this on the operator's Mac")
    today, parcels, unmatched, failed = date.today(), [], [], []
    with PoliteClient(ScrapingSettings.from_env()) as client:
        for name in args.counties:
            try:
                found, missing = collect(client, COUNTIES[name], today)
            except Exception as exc:  # noqa: BLE001 - one county's failure keeps its previous rows
                print(f"{name}: FAILED ({type(exc).__name__}: {exc}); its previous snapshot rows are kept", flush=True)
                failed.append(name)
                continue
            parcels += found
            unmatched += missing
            print(f"{name}: {len(found)} parcels, {len(missing)} without a matching parcel", flush=True)
    previous = json.loads(args.output.read_text()) if args.output.exists() else {"parcels": []}
    # Counties not collected this time (failed, or not asked for) keep their previous rows.
    parcels += [parcel for parcel in previous["parcels"]
                if parcel["county"] in failed or parcel["county"] not in args.counties]
    for line in unmatched:
        print(f"not matched: {line}")
    snapshot = {"source_system": "ga_county_tax_sale", "state": "GA", "scraped_at": datetime.now(timezone.utc).isoformat(),
                "parser_version": PARSER_VERSION, "counties": sorted(args.counties), "failed": failed,
                "parcels": parcels, "unmatched": unmatched}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, indent=1) + "\n")
    print(f"Georgia: {len(parcels)} parcels -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
