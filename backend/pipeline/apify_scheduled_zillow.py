"""One-batch scheduled-property enrichment; checkpoint before submitting paid work."""
import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
import time

import httpx
from sqlalchemy import text
from dotenv import load_dotenv

from app.auth import TARGET_COUNTY_KEYS
from app.database.session import engine
from pipeline.fill_missing_zips import search_city

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = Path(os.environ.get("APIFY_OUTPUT_DIR", ROOT / ".local/apify-zillow-scheduled"))
ACTOR = "maxcopell~zillow-detail-scraper"
API = "https://api.apify.com/v2"
TARGET_STATE = os.environ.get("APIFY_STATE")
# Sales whose status contains this text; "sold_or_cancelled" covers a recently held sale.
TARGET_STATUS = os.environ.get("APIFY_STATUS", "scheduled")
EXPECTED_COUNT = os.environ.get("APIFY_EXPECTED_COUNT")

load_dotenv(ROOT / "backend/.env")


def save(name, value):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / name
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, default=str) + "\n")
    temp.replace(path)


STREET_SUFFIX = re.compile(
    r"\b(?:Avenue|Ave|Street|St|Road|Rd|Drive|Dr|Lane|Ln|Court|Ct|Place|Pl|Boulevard|Blvd|"
    r"Way|Terrace|Ter|Circle|Cir|Run|Pike|Highway|Hwy|Trail|Parkway|Pkwy|Square|Sq|Alley|"
    r"Turnpike|Tpke|Crossing|Xing|Loop|Path|Plaza|Row)\b\.?", re.IGNORECASE)
NEXT_SUFFIX = re.compile(r"\s+" + STREET_SUFFIX.pattern, re.IGNORECASE)
UNIT = re.compile(r"^\s*,?\s*((?:Unit|Apt\.?|Apartment|Suite|Ste\.?|#)\s*[\w-]+)", re.IGNORECASE)
# Queens house numbers are "<cross street>-<house>" ("37-46 79th Street"); some sources
# drop the hyphen ("9745 86TH ST"), and the house part is then the last two digits. Four
# unhyphenated digits are a plain number unless a numbered street follows: Ridgewood's
# "1654 George Street" is 1654.
QUEENS_NUMBER = re.compile(r"^(\d{2,3})\s*-\s*(\d{2})\b|^(\d{3})(\d{2})\b|^(\d{2})(\d{2})(?=\s+\d+(?:st|nd|rd|th)\b)",
                           re.IGNORECASE)
SHORT_SUFFIX = {"street": "St", "avenue": "Ave", "road": "Rd", "place": "Pl", "boulevard": "Blvd",
                "drive": "Dr", "lane": "Ln", "court": "Ct", "parkway": "Pkwy", "terrace": "Ter"}


ORDINALS = {word: f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"
            for n, word in enumerate(["first", "second", "third", "fourth", "fifth", "sixth", "seventh",
                                      "eighth", "ninth", "tenth", "eleventh", "twelfth", "thirteenth",
                                      "fourteenth", "fifteenth", "sixteenth", "seventeenth", "eighteenth",
                                      "nineteenth", "twentieth"], start=1)}
# "Second Avenue" -> "2nd Avenue": Zillow lists numbered streets in digits.
ORDINAL_WORD = re.compile(r"\b(?:" + "|".join(ORDINALS) + r")\b(?=\s+" + STREET_SUFFIX.pattern + ")",
                          re.IGNORECASE)


def whole_range(first, second):
    """A full range ("8-10", "7-06" in Fair Lawn) is how Zillow lists the lot; an abbreviated one
    ("8155-57") is not, so it is cut to the first number."""
    return second.startswith("0") or (len(second) >= len(first) and int(second) > int(first))


def is_queens(row):
    return row.get("state") == "NY" and str(row.get("county") or "").strip().lower() == "queens"


def queens_street(street):
    """A Queens street as Zillow lists it: hyphenated house number and short suffix
    ("37-46 79th Street" -> "37-46 79th St", "9745 86TH ST" -> "97-45 86TH ST")."""
    return short_suffix(QUEENS_NUMBER.sub(lambda m: "-".join(part for part in m.groups() if part),
                                          clean_street(street, keep_hyphen=True), count=1))


def short_suffix(street):
    """The last street suffix in its short form ("79th Street" -> "79th St")."""
    suffixes = list(STREET_SUFFIX.finditer(street))
    if suffixes and (short := SHORT_SUFFIX.get(suffixes[-1].group(0).rstrip(".").lower())):
        street = street[:suffixes[-1].start()] + short + street[suffixes[-1].end():]
    return street


def clean_street(street, keep_hyphen=False):
    """Strip court-notice noise from a street line for a Zillow address search.

    Drops "A/K/A ..." aliases, parentheticals and trailing municipality text
    ("East Pennsboro - Township Enola"), keeps a unit, and reduces a house
    number range ("8155-57") to its first number unless keep_hyphen (Queens) or it is
    a full range ("8-10"). Numbered streets become digits and "CO RD Y" becomes "County Road Y"."""
    street = re.split(r"\b(?:A/K/A|AKA|F/K/A|Is Also Known As|Also Known As)\b|\(|,(?!\s*(?:Unit|Apt|#))",
                      street or "", maxsplit=1, flags=re.IGNORECASE)[0]
    street = re.sub(r"^Mailing Address:\s*", "", street.strip(), flags=re.IGNORECASE)
    street = re.sub(r"^(\d+)\s*-\s*(\d+)\b", lambda m: f"{m[1]}-{m[2]}" if keep_hyphen or (
        whole_range(m[1], m[2])) else m[1], street)
    street = re.sub(r"\bCO\.?\s+RD\b\.?", "County Road", street, flags=re.IGNORECASE)
    street = ORDINAL_WORD.sub(lambda m: ORDINALS[m[0].lower()], street)
    # The suffix ends the street name unless it directly follows the house
    # number ("830 Avenue A"); anything after it except a unit is noise.
    for match in STREET_SUFFIX.finditer(street):
        if re.fullmatch(r"\d+\s*", street[:match.start()]):
            continue
        end = match.end()
        # "West Terrace Drive": a following suffix word is still the street name.
        while following := NEXT_SUFFIX.match(street, end):
            end = following.end()
        # "County Road Y": the route letter or number belongs to the name.
        route = re.compile(r"\s+[A-Z0-9]{1,4}\b", re.IGNORECASE).match(street, end)
        if route and re.search(r"\bCounty\s+$", street[:match.start()], re.IGNORECASE):
            end = route.end()
        unit = UNIT.match(street[end:])
        street = street[:end] + (f" {unit.group(1)}" if unit else "")
        break
    return re.sub(r"\s+", " ", street).strip(" ,.")


def search_address(row):
    """Street, state and ZIP (Zillow resolves these better than court town names such as
    "Winslow Township"), or the city when there is no ZIP. Periods are dropped
    ("3034 N. 56TH ST." -> "3034 N 56TH ST") and a placeholder city ("Unincorporated") is left out.
    Queens streets keep their hyphenated house number (queens_street)."""
    street = queens_street(row["street_address"]) if is_queens(row) else clean_street(row["street_address"])
    street = re.sub(r"\s+", " ", street.replace(".", " ")).strip()
    city = search_city(row.get("city"))
    if re.match(r"\d+-\d+ ", street) and not is_queens(row) and city and row.get("zip_code"):
        # Zillow finds a full range ("8-10 Sandford Ave, Plainfield, NJ 07060") only
        # with the town and a short suffix.
        return f"{short_suffix(street)}, {city}, {row['state']} {row['zip_code']}"
    if row.get("zip_code"):
        return f"{street}, {row['state']} {row['zip_code']}"
    return ", ".join(part for part in (street, city, row["state"]) if part)


def queens_retry_address(row):
    """A Queens house the hyphenated search missed: Zillow lists many under the number without
    its hyphen and the town ("33-21 102nd Street" -> "3321 102nd St, Corona, NY 11368")."""
    street = re.sub(r"^(\d+)-(\d+)", r"\1\2", search_address(row).split(",")[0])
    return ", ".join(part for part in (street, search_city(row.get("city")), f"NY {row.get('zip_code') or ''}".strip()) if part)


def first_pass_address(row):
    """The normalized address without commas, plus the ZIP when it lacks one (e.g. a ZIP
    filled in later by fill_missing_zips). Queens addresses use search_address: Zillow files
    Queens houses under a different neighborhood than court notices name, so the town makes
    the search miss, and it finds "37-46 79th St, NY 11372" but not "37-46 79th Street ..."."""
    if is_queens(row):
        return search_address(row)
    address = re.sub(r"\s*,\s*", " ", row["normalized_address"]).strip()
    if row.get("zip_code") and not re.search(r"\b\d{5}\b", address):
        address = f"{address} {row['zip_code']}"
    return address


def searchable(row):
    """False for rows Zillow cannot resolve to one house: a placeholder street number
    ("0 UNKNOWN") or several addresses in one listing ("205 NW 89TH ST & 432 Larkspur Ln",
    "20-24 and 20-26 Steinway Street")."""
    street = row.get("street_address") or ""
    return (bool(re.match(r"[1-9]", street)) and " & " not in f"{street} {row.get('normalized_address') or ''}"
            and not re.match(r"[\d-]+\s+and\s+\d", street, re.IGNORECASE))


def prepare(only_missing=False, retry_unmatched=False, sold_results=False, buyer=None, queens_retry=False):
    """queens_retry: unmatched Queens properties searched again as queens_retry_address, each
    only once (a property already searched in that form is not sent again)."""
    retry_unmatched = retry_unmatched or queens_retry
    if (OUTPUT / "submission.json").exists():
        raise RuntimeError("A submission already exists. Resume it; do not replace its manifest.")
    with engine.connect() as connection:
        rows = connection.execute(text("""
            SELECT p.id::text AS property_id, ss.id::text AS sheriff_sale_id, ss.county,
                   p.normalized_address, p.street_address, p.city, p.state, p.zip_code,
                   ss.current_status, ss.current_sale_date
            FROM sheriff_sales ss JOIN properties p ON p.id=ss.property_id
            WHERE (:state IS NULL OR p.state=:state)
              -- Only the target counties are enriched (app.auth.TARGET_COUNTIES).
              AND UPPER(p.state) || ':' || LOWER(TRIM(p.county)) = ANY(:target_counties)
              AND p.valuation_excluded_reason IS NULL
              AND (CASE WHEN :sold_results THEN ss.sold_buyer IS NOT NULL ELSE strpos(LOWER(CASE
                WHEN ss.source_system IN ('nyc_kings_court_foreclosure_index',
                    'fl_hillsborough_published_foreclosure_notice', 'tx_county_clerk_trustee_sale')
                    AND ss.current_sale_date<CURRENT_DATE
                    AND ss.current_status='scheduled_unverified'
                THEN 'date_passed_unverified' ELSE ss.current_status END), :status) > 0 END)
              AND (CAST(:buyer AS TEXT) IS NULL OR ss.sold_buyer = :buyer)
              AND (NOT :only_missing OR NOT EXISTS (
                SELECT 1 FROM apify_zillow_results z
                WHERE z.property_id=p.id AND z.is_current
                  AND z.match_status IN ('matched','invalid')))
              AND (NOT :retry_unmatched OR NOT EXISTS (
                SELECT 1 FROM apify_zillow_results z
                WHERE z.property_id=p.id AND z.is_current AND z.match_status='matched'
                  AND LOWER(COALESCE(z.raw_payload->>'isValid', 'true')) <> 'false'))
            ORDER BY p.normalized_address, ss.id
        """), {"state": TARGET_STATE, "status": TARGET_STATUS, "only_missing": only_missing,
                "retry_unmatched": retry_unmatched, "sold_results": sold_results, "buyer": buyer,
                "target_counties": sorted(TARGET_COUNTY_KEYS)}).mappings().all()
    manifest = [dict(row) for row in rows if searchable(row)]
    if queens_retry:
        manifest = [row for row in manifest if is_queens(row)]
        with engine.connect() as connection:
            tried = {(str(property_id), address) for property_id, address in connection.execute(text(
                """SELECT property_id, submitted_address FROM apify_zillow_results
                   WHERE property_id = ANY(CAST(:ids AS uuid[]))"""), {"ids": [r["property_id"] for r in manifest]})}
        manifest = [row for row in manifest if (row["property_id"], queens_retry_address(row)) not in tried]
    for row in manifest:
        if retry_unmatched:
            row["input_address"] = queens_retry_address(row) if is_queens(row) else search_address(row)
        else:
            # Normalized addresses sometimes split multi-word towns ("West New, York");
            # Zillow's free-text search matches better without the commas.
            row["input_address"] = first_pass_address(row)
    if any(not row["input_address"] for row in manifest):
        raise RuntimeError("Blank input address; review manifest before submitting.")
    save("manifest.json", manifest)
    save("input.json", {"addresses": sorted({row["input_address"] for row in manifest})})
    print(json.dumps({"rows": len(manifest), "distinct_properties": len({r['property_id'] for r in manifest}),
                      "distinct_addresses": len({r['input_address'] for r in manifest}),
                      "statuses": sorted({r['current_status'] for r in manifest})}), flush=True)


def client():
    token = os.environ.get("APIFY_API_TOKEN")
    if not token:
        raise RuntimeError("APIFY_API_TOKEN is missing")
    return httpx.Client(base_url=API, headers={"Authorization": f"Bearer {token}"}, timeout=120)


def get(client, path, **kwargs):
    for attempt in range(4):
        try:
            response = client.get(path, **kwargs)
            response.raise_for_status()
            return response.json()
        except (httpx.TransportError, httpx.HTTPStatusError):
            if attempt == 3:
                raise
            time.sleep(15)


def submit():
    marker = OUTPUT / "submission.json"
    if marker.exists():
        raise RuntimeError("Submission marker exists; use watch, never submit twice.")
    payload = json.loads((OUTPUT / "input.json").read_text())
    if EXPECTED_COUNT and len(payload["addresses"]) != int(EXPECTED_COUNT):
        raise RuntimeError(f"Expected {EXPECTED_COUNT} addresses; found {len(payload['addresses'])}. Review before submitting.")
    with client() as api:
        # Exclusive creation protects against concurrent/double submission. No POST retries.
        with marker.open("x") as handle:
            json.dump({"submitted_at": datetime.now(timezone.utc).isoformat(),
                       "actor": ACTOR, "count": len(payload["addresses"]),
                       "status": "SUBMITTING"}, handle)
        response = api.post(f"/acts/{ACTOR}/runs", json=payload)
        response.raise_for_status()
        run = response.json()["data"]
        save("run.json", run)
        save("submission.json", {"run_id": run["id"], "actor": ACTOR,
                                 "count": len(payload["addresses"]), "status": run["status"]})
        print(json.dumps({"run_id": run["id"], "status": run["status"]}), flush=True)


def watch():
    run = json.loads((OUTPUT / "run.json").read_text())
    with client() as api:
        while True:
            run = get(api, f"/actor-runs/{run['id']}")["data"]
            save("run.json", run)
            print(f"{datetime.now(timezone.utc).isoformat()} {run['id']} {run['status']}", flush=True)
            if run["status"] == "SUCCEEDED":
                break
            if run["status"] in {"FAILED", "ABORTED", "TIMED-OUT"}:
                raise RuntimeError(f"Run ended with {run['status']}; no new run was submitted.")
            time.sleep(15)
        dataset = run["defaultDatasetId"]
        metadata = get(api, f"/datasets/{dataset}")["data"]
        save("dataset-metadata.json", metadata)
        items = []
        while True:
            batch = get(api, f"/datasets/{dataset}/items", params={
                "format": "json", "offset": len(items), "limit": 1000,
            })
            if not batch:
                break
            items.extend(batch)
        save("dataset.json", items)
        if len(items) != metadata["itemCount"]:
            # Apify's metadata can lag briefly while an actor finalizes its
            # dataset. The downloaded endpoint is authoritative here; retain
            # the discrepancy for auditability without discarding valid items.
            metadata["downloadedItemCount"] = len(items)
            save("dataset-metadata.json", metadata)
            print(f"Dataset metadata reported {metadata['itemCount']}; downloaded {len(items)} items.", flush=True)
        print(f"Saved all {len(items)} items to {OUTPUT / 'dataset.json'}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "submit", "watch"])
    parser.add_argument("--only-missing", action="store_true",
                        help="prepare: skip properties that already have a current matched Zestimate")
    parser.add_argument("--retry-unmatched", action="store_true",
                        help="prepare: only properties Zillow had no data for or matched to the wrong "
                             "house, searched again by cleaned street and ZIP")
    parser.add_argument("--queens-retry", action="store_true",
                        help="prepare: unmatched Queens properties not yet searched without the hyphen and with the town")
    parser.add_argument("--sold-results", action="store_true",
                        help="prepare: sold sales with a parsed result (pipeline.sale_results) instead of a status")
    parser.add_argument("--buyer", choices=["third_party", "plaintiff", "cwpp", "not_stated"],
                        help="prepare with --sold-results: only sales this buyer won (analytics compare third-party bids)")
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.only_missing, args.retry_unmatched, args.sold_results, args.buyer, args.queens_retry)
    else:
        {"submit": submit, "watch": watch}[args.action]()
