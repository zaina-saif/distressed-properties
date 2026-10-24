"""Arizona trustee sales from the county recorder (Maricopa and Pima; other counties by config).

Stages, each resumable and safe to rerun:
  1. index   the recorder's JSON search for notices of trustee's sale, cancellations of
             them and trustee's deeds, week by week (pipeline.az_recorder.RecorderIndex),
             merged by recording number into .local/az-recorder/<county>/index.json
  2. import  PDFs the operator saved from the recorder's website (--import-folder), matched to
             their recording number by file name or by the number printed on the document, and
             copied into .local/az-recorder/<county>/pdf/. --todo lists what is still missing,
             with each document's details-page link ("PDF - All pages" downloads it).
             Maricopa serves every document PDF from legacy.recorder.maricopa.gov/recdocdata/,
             which its robots.txt disallows, so the automated fetch (--fetch, DocumentFetcher)
             stops there; it is kept for counties whose recorder allows it.
  3. ocr     positioned OCR lines per document, cached in .local/az-recorder/<county>/ocr/
  4. parse   pipeline.parse_az_trustee_documents (no trustor or grantee names)
  5. link    pipeline.az_trustee_lifecycle: foreclosures with noticed/postponed/cancelled/sold
  6. parcels the county assessor's parcel layer by APN, else by address (pipeline.az_assessor)
  7. output  data/sheriff_sales/az_<county>_trustee_sales.json (parsed fields only) and a
             report in the run dir: counts by status, parse success, samples, known gaps

A `manual_export` recorder (Pima: its Tyler EagleWeb portal answers scripted searches with an
AWS WAF human-verification page, see docs/arizona/pima-recorder.md) has no index to query: the
operator saves the documents from a normal browser and --import-folder builds the index from
the PDFs themselves, the recording number from the file name (else the recorder's stamp), the
recording date from the stamp and the kind from the document's title. Stages 3-7 are the same.

The PDFs and OCR text (which do contain borrowers' names) stay in .local/; only the
parsed property, sale, loan, trustee and beneficiary fields reach the snapshot.

    python -m pipeline.scrape_az_trustee_sales --dry-run                          # index the last 3 days only
    python -m pipeline.scrape_az_trustee_sales --backfill --todo todo.csv         # index 120 days, list what to save
    python -m pipeline.scrape_az_trustee_sales --import-folder ~/Downloads/maricopa  # daily: last 3 days + saved PDFs
    python -m pipeline.scrape_az_trustee_sales --from 2026-07-01 --to 2026-07-31
    python -m pipeline.load_az_trustee_sales
    python -m pipeline.scrape_az_trustee_sales --county Pima --import-folder ~/Downloads/pima  # weekly, saved PDFs
    python -m pipeline.load_az_trustee_sales --county Pima
"""
import argparse
import csv
import json
import re
import shutil
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from pipeline import ocr_engines
from pipeline.az_assessor import ParcelLayer
from pipeline.az_recorder import CountyConfig, DocumentFetcher, RecorderIndex, county_config
from pipeline.az_trustee_lifecycle import Foreclosure, link
from pipeline.parse_az_trustee_documents import parse_cancellation, parse_notice, parse_trustee_deed
from pipeline.scraping.http import PoliteClient

PARSER_VERSION = "az_recorder_trustee_v1"
SOURCE_SYSTEM = "az_county_recorder_trustee_sale"
PARSED_OK = 0.8  # a notice at or above this confidence, with an address and a sale date, counts as parsed


def output_path(county: CountyConfig) -> Path:
    return Path(f"data/sheriff_sales/az_{county.slug.replace('-', '_')}_trustee_sales.json")


def load_index(county: CountyConfig) -> dict[str, dict]:
    path = county.cache / "index.json"
    return json.loads(path.read_text()) if path.exists() else {}


def save_index(county: CountyConfig, index: dict[str, dict]) -> None:
    path = county.cache / "index.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(sorted(index.items())), indent=0) + "\n")


def ocr_lines(county: CountyConfig, recording_number: str) -> list[str] | None:
    path = county.cache / "ocr" / f"{recording_number}.txt"
    return path.read_text().splitlines() if path.exists() else None


def run_ocr(county: CountyConfig, pdfs: list[Path], engine_name: str, workers: int) -> int:
    engine = ocr_engines.engine(engine_name)
    folder = county.cache / "ocr"
    folder.mkdir(parents=True, exist_ok=True)
    todo = [pdf for pdf in pdfs if not (folder / f"{pdf.stem}.txt").exists()]

    def one(pdf: Path) -> None:
        try:
            (folder / f"{pdf.stem}.txt").write_text("\n".join(ocr_engines.text_lines(engine.boxes(pdf))))
        except Exception as exc:  # noqa: BLE001 - reported, the rest go on
            print(f"  ! OCR {pdf.stem}: {exc}", flush=True)

    with ThreadPoolExecutor(workers) as pool:
        for done, _ in enumerate(pool.map(one, todo), 1):
            if done % 50 == 0:
                print(f"  OCR {done}/{len(todo)}", flush=True)
    return len(todo)


DETAILS = "https://recorder.maricopa.gov/recording/document-details.html?recordingNumber={}"


def import_folder(county: CountyConfig, index: dict[str, dict], folder: Path, engine_name: str) -> dict:
    """Copy saved PDFs into the cache under their recording number: an indexed 11-digit number in
    the file name, else the indexed number printed on the document (the recorder stamps it on
    every page). The OCR made to find it is kept, so the document is not read twice."""
    engine = ocr_engines.engine(engine_name)
    (county.cache / "pdf").mkdir(parents=True, exist_ok=True)
    (county.cache / "ocr").mkdir(parents=True, exist_ok=True)
    counts, unmatched = Counter(), []
    for pdf in sorted(folder.expanduser().glob("*.pdf")):
        named = [number for number in re.findall(r"(?<!\d)(\d{11})(?!\d)", pdf.stem) if number in index]
        lines = None
        if not named:
            lines = ocr_engines.text_lines(engine.boxes(pdf))
            named = list(dict.fromkeys(number for line in lines
                                       for number in re.findall(r"(?<!\d)(\d{11})(?!\d)", line) if number in index))
        if len(named) != 1:
            unmatched.append(pdf.name)
            continue
        target = county.cache / "pdf" / f"{named[0]}.pdf"
        if target.exists():
            counts["already_imported"] += 1
            continue
        shutil.copyfile(pdf, target)
        if lines is not None:
            (county.cache / "ocr" / f"{named[0]}.txt").write_text("\n".join(lines))
        counts["imported"] += 1
    return {**counts, "unmatched": unmatched}


# Document titles, in the order they are tried on a line: a cancellation's title contains a notice's.
TITLES = [("cancellation", re.compile(r"(?i)cancell?ation\s+of\s+(?:the\s+)?notice\s+of\s+trustee.?s\s+sale"
                                      r"|notice\s+of\s+cancell?ation\s+of\s+trustee.?s\s+sale")),
          ("trustee_deed", re.compile(r"(?i)trustee.?s\s+deed")),
          ("notice", re.compile(r"(?i)notice\s+of\s+trustee.?s\s+sale"))]
STAMP_DATE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\s+\d{1,2}:\d{2}\s*[AP]\.?M\b", re.I)


def recorder_stamp(lines: list[str]) -> tuple[str | None, date | None]:
    """The recording number and date the recorder stamps at the top of the first page
    ("20262940537" / "10/21/2026 03:52 PM | Page 1 of 3")."""
    head = " ".join(lines[:12])
    number = re.search(r"(?<!\d)(20\d{9})(?!\d)", head)
    stamped = STAMP_DATE.search(head)
    try:
        recorded = datetime.strptime(stamped.group(1), "%m/%d/%Y").date() if stamped else None
    except ValueError:
        recorded = None
    return (number.group(1) if number else None), recorded


def document_kind(lines: list[str]) -> str | None:
    """notice, cancellation or trustee_deed, from the first title in the document's first 40 lines."""
    for line in lines[:40]:
        for kind, title in TITLES:
            if title.search(line):
                return kind
    return None


def import_exported(county: CountyConfig, index: dict[str, dict], folder: Path, engine_name: str) -> dict:
    """Index and copy PDFs saved from a manual_export recorder. A PDF whose recording number,
    recording date or kind cannot be read is reported, not indexed."""
    engine = ocr_engines.engine(engine_name)
    (county.cache / "pdf").mkdir(parents=True, exist_ok=True)
    (county.cache / "ocr").mkdir(parents=True, exist_ok=True)
    counts, unrecognised = Counter(), []
    for pdf in sorted(folder.expanduser().glob("*.pdf")):
        named = re.findall(r"(?<!\d)(\d{11})(?!\d)", pdf.stem)
        if len(named) == 1 and named[0] in index and (county.cache / "pdf" / f"{named[0]}.pdf").exists():
            counts["already_imported"] += 1
            continue
        lines = ocr_engines.text_lines(engine.boxes(pdf))
        stamped, recorded = recorder_stamp(lines)
        number = named[0] if len(named) == 1 else stamped
        kind = document_kind(lines)
        missing = [name for name, value in (("recording number", number), ("recording date", recorded), ("title", kind))
                   if not value]
        if missing:
            unrecognised.append(f"{pdf.name}: no {', '.join(missing)}")
            continue
        shutil.copyfile(pdf, county.cache / "pdf" / f"{number}.pdf")
        (county.cache / "ocr" / f"{number}.txt").write_text("\n".join(lines))
        index[number] = {"recording_number": number, "recording_date": recorded.isoformat(),
                         "document_code": "manual_export", "kind": kind}
        counts[kind] += 1
    return {**counts, "unrecognised": unrecognised}


def write_todo(county: CountyConfig, index: dict[str, dict], path: Path) -> int:
    """The indexed documents without a saved PDF, notices first and newest first."""
    order = {"notice": 0, "cancellation": 1, "trustee_deed": 2}
    missing = sorted((row for row in index.values() if not (county.cache / "pdf" / f"{row['recording_number']}.pdf").exists()),
                     key=lambda row: row["recording_date"], reverse=True)
    missing.sort(key=lambda row: order[row["kind"]])
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["kind", "recording_number", "recording_date", "details_page"])
        writer.writerows([row["kind"], row["recording_number"], row["recording_date"], DETAILS.format(row["recording_number"])]
                         for row in missing)
    return len(missing)


def fetch_documents(county: CountyConfig, index: dict[str, dict], assisted: bool, limit: int | None) -> Counter:
    order = {"notice": 0, "cancellation": 1, "trustee_deed": 2}
    todo = sorted((row for row in index.values() if not row.get("unavailable")
                   and not (county.cache / "pdf" / f"{row['recording_number']}.pdf").exists()),
                  key=lambda row: row["recording_date"], reverse=True)
    todo.sort(key=lambda row: order[row["kind"]])  # notices first, newest first within each kind
    todo = todo[:limit] if limit else todo
    counts = Counter()
    if not todo:
        return counts
    print(f"  fetching {len(todo)} documents (about {len(todo) * 2.6 / 60:.0f} min)", flush=True)
    with DocumentFetcher(county, assisted=assisted) as fetcher:
        for done, row in enumerate(todo, 1):
            path = fetcher.fetch(row["recording_number"])
            if path is None:
                row["unavailable"] = True
                counts["unavailable"] += 1
            else:
                counts["fetched"] += 1
            if done % 100 == 0:
                save_index(county, index)
                print(f"  fetched {done}/{len(todo)}", flush=True)
    save_index(county, index)
    return counts


def sharper_notice(county: CountyConfig, row: dict, first: dict) -> dict:
    """A second, sharper OCR pass (cached as ocr/<n>.hi.txt) for a notice read without a sale date;
    the better-scoring reading wins. Only macOS has this pass."""
    if "sale_date" not in first["missing"] or not shutil.which("swiftc"):
        return first
    pdf = county.cache / "pdf" / f"{row['recording_number']}.pdf"
    cached = county.cache / "ocr" / f"{row['recording_number']}.hi.txt"
    if not cached.exists():
        if not pdf.exists():
            return first
        cached.write_text("\n".join(ocr_engines.text_lines(ocr_engines.MacVisionOcr(5600, correct=True).boxes(pdf))))
    second = parse_notice(cached.read_text().splitlines(), row["recording_number"], date.fromisoformat(row["recording_date"]),
                          county.recorder)
    return second if second["confidence"] > first["confidence"] else first


def parse_all(county: CountyConfig, index: dict[str, dict]) -> dict[str, list[dict]]:
    rules = county.recorder
    parsed = {"notice": [], "cancellation": [], "trustee_deed": [], "other_trustee_deed": [], "unread": []}
    for row in index.values():
        lines = ocr_lines(county, row["recording_number"])
        if lines is None:
            parsed["unread"].append(row)
            continue
        recorded = date.fromisoformat(row["recording_date"])
        base = {"recording_number": row["recording_number"], "recording_date": row["recording_date"]}
        if row["kind"] == "notice":
            result = sharper_notice(county, row, parse_notice(lines, row["recording_number"], recorded, rules))
            parsed["notice"].append({**base, **result})
        elif row["kind"] == "cancellation":
            parsed["cancellation"].append({**base, **parse_cancellation(lines, row["recording_number"], rules)})
        else:
            deed = {**base, **parse_trustee_deed(lines, row["recording_number"], recorded, rules=rules)}
            parsed["trustee_deed" if deed["upon_sale"] else "other_trustee_deed"].append(deed)
    return parsed


def place(foreclosure: Foreclosure, parcels: dict[str, dict], layer: ParcelLayer) -> tuple[dict | None, str | None, dict | None]:
    """(address, where it came from, parcel). The parcel layer's situs wins when its house number
    agrees with the notice's (or the notice has none); otherwise the notice's address is kept."""
    notice = foreclosure.notice
    parcel = parcels.get(notice.get("apn") or "")
    stated = notice.get("address")
    if parcel is None and stated:
        parcel = layer.by_address(stated["street"], stated["city"])
    house = lambda street: (re.match(r"\d+", street or "") or [None])[0]
    # Pima's layer has no postal city: the notice's city goes with the assessor's street.
    city = (parcel or {}).get("city") or (stated or {}).get("city")
    # The house numbers agree, or the notice's street is OCR debris that still holds the parcel's
    # house number ("18 THEREOF. Purported Streer Address: 1221 E. PARK ESTATES CIR").
    agrees = lambda: not stated or house(stated["street"]) == house(parcel["street"]) or \
        house(parcel["street"]) in re.findall(r"\d+", stated["street"])
    if parcel and parcel.get("street") and city and agrees():
        return {"street": parcel["street"], "city": city, "zip": parcel["zip"] or (stated or {}).get("zip")}, "assessor", parcel
    if stated:
        return stated, "notice", parcel
    return None, None, parcel


def foreclosure_record(foreclosure: Foreclosure, address: dict, address_source: str, parcel: dict | None,
                       checks: dict) -> dict:
    notice = foreclosure.notice
    check = checks.get(foreclosure.key)
    sale_date = notice.get("sale_date")
    earlier = foreclosure.earlier_sale_dates
    lifecycle = foreclosure.lifecycle
    if check and check.get("sale_date") and sale_date and check["sale_date"] > sale_date and lifecycle in ("noticed", "postponed"):
        earlier, sale_date, lifecycle = earlier + [sale_date], check["sale_date"], "postponed"
    deed = foreclosure.deed
    return {
        "key": foreclosure.key, "lifecycle": lifecycle,
        "street": address["street"], "city": address["city"], "zip": address.get("zip"), "address_source": address_source,
        "notice_address": notice.get("address"),
        "apn": notice.get("apn") or (parcel or {}).get("apn"),
        "sale_date": sale_date, "sale_time": notice.get("sale_time"), "sale_location": notice.get("sale_location"),
        "earlier_sale_dates": earlier,
        "original_principal": notice.get("original_principal"), "opening_bid": (check or {}).get("opening_bid"),
        "deed_of_trust": notice.get("deed_of_trust"), "deed_of_trust_recorded": notice.get("deed_of_trust_recorded"),
        "legal_description": notice.get("legal_description"), "ts_number": notice.get("ts_number"),
        "trustee": notice.get("trustee"), "trustee_phone": notice.get("trustee_phone"),
        "beneficiary": notice.get("beneficiary"), "sale_info_websites": notice.get("sale_info_websites"),
        "notices": [{"recording_number": n["recording_number"], "recording_date": n["recording_date"],
                     "sale_date": n.get("sale_date")} for n in foreclosure.notices],
        "cancellation": ({key: foreclosure.cancellation.get(key) for key in ("recording_number", "recording_date", "dated")}
                         if foreclosure.cancellation else None),
        "trustee_deed": ({key: deed.get(key) for key in ("recording_number", "recording_date", "sold_on", "price", "buyer")}
                         if deed else None),
        "links": foreclosure.links, "confidence": notice.get("confidence"), "missing": notice.get("missing"),
        "status_check": check,
        "assessor": ({key: parcel.get(key) for key in ("apn", "full_cash_value", "limited_value", "tax_year", "use_code",
                                                       "legal_class", "owner_occupied", "latitude", "longitude",
                                                       "deed_number")} if parcel else None),
    }


def report(parsed: dict, foreclosures: dict, records: list[dict], unplaced: list[str], unlinked: list[dict],
           index: dict, fetched: Counter) -> dict:
    notices = parsed["notice"]
    ok = [n for n in notices if n["confidence"] >= PARSED_OK and n.get("address") and n.get("sale_date")]
    missing = Counter(field for n in notices for field in n["missing"])
    trustees = Counter(r["trustee"] or "(not read)" for r in records if r["lifecycle"] in ("noticed", "postponed"))
    sites = Counter(site.split("/")[0].removeprefix("www.") for r in records if r["lifecycle"] in ("noticed", "postponed")
                    for site in r["sale_info_websites"] or [])
    upcoming = [r for r in records if r["lifecycle"] in ("noticed", "postponed") and r["sale_date"]
                and r["sale_date"] >= date.today().isoformat()]
    return {
        "indexed": dict(Counter(row["kind"] for row in index.values())),
        "documents_this_run": dict(fetched),
        "unavailable_documents": sum(1 for row in index.values() if row.get("unavailable")),
        "not_yet_read": dict(Counter(row["kind"] for row in parsed["unread"])),
        "parsed": {"notices": len(notices), "cancellations": len(parsed["cancellation"]),
                   "trustee_deeds_upon_sale": len(parsed["trustee_deed"]),
                   "other_trustee_deeds_skipped": len(parsed["other_trustee_deed"])},
        "notice_parse_success": {"parsed": len(ok), "of": len(notices),
                                 "rate": round(len(ok) / len(notices), 3) if notices else None,
                                 "fields_missing": dict(missing.most_common())},
        "foreclosures": len(foreclosures),
        "by_status": dict(Counter(r["lifecycle"] for r in records)),
        "upcoming_sales": len(upcoming),
        "address_source": dict(Counter(r["address_source"] for r in records)),
        "with_assessor_data": sum(1 for r in records if r["assessor"]),
        "owner_occupied": sum(1 for r in records if (r["assessor"] or {}).get("owner_occupied")),
        "without_address": unplaced[:50], "without_address_count": len(unplaced),
        "unlinked_events": dict(Counter(event["kind"] for event in unlinked)),
        "trustees_upcoming": dict(trustees.most_common(15)),
        "sale_info_websites_upcoming": dict(sites.most_common(10)),
        "samples": [{key: r[key] for key in ("lifecycle", "street", "city", "zip", "apn", "sale_date", "trustee",
                                             "original_principal", "assessor", "links")} for r in records[:: max(1, len(records) // 4)][:4]],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--county", default="Maricopa")
    parser.add_argument("--from", dest="start", type=date.fromisoformat)
    parser.add_argument("--to", dest="end", type=date.fromisoformat)
    parser.add_argument("--days", type=int, default=3, help="index the last N days (default 3: a daily run with overlap)")
    parser.add_argument("--backfill", action="store_true", help="index the last backfill_days (config) days")
    parser.add_argument("--dry-run", action="store_true", help="query the index only and print counts; write nothing")
    parser.add_argument("--import-folder", type=Path, help="a folder of PDFs saved from the recorder's website")
    parser.add_argument("--todo", type=Path, help="write the indexed documents still without a PDF to this CSV")
    parser.add_argument("--fetch", action="store_true",
                        help="fetch PDFs automatically (stops where robots.txt disallows it, as for Maricopa)")
    parser.add_argument("--assisted", action="store_true", help="with --fetch: show the browser window")
    parser.add_argument("--limit", type=int, help="with --fetch: at most this many documents")
    parser.add_argument("--ocr-engine", help="macos, tesseract or auto (config default)")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--run-dir", type=Path, default=Path("../.local/az-recorder/runs"))
    args = parser.parse_args(argv)
    county = county_config(args.county)
    end = args.end or date.today()
    start = args.start or end - timedelta(days=(int(county.settings["backfill_days"]) if args.backfill else args.days))
    settings = county.scraping_settings()

    manual = county.recorder["kind"] == "manual_export"
    if manual and (args.fetch or args.todo):
        raise SystemExit(f"{county.name}: documents are saved by hand (manual_export); use --import-folder")

    with PoliteClient(settings) as client:
        index = load_index(county)
        if manual and args.dry_run:
            saved = sorted(args.import_folder.expanduser().glob("*.pdf")) if args.import_folder else []
            print(json.dumps({"county": county.name, "indexed": dict(Counter(row["kind"] for row in index.values())),
                              "pdfs_in_folder": len(saved)}, indent=2))
            return 0
        found = [] if manual else RecorderIndex(county, client).recordings(start, end)
        if args.dry_run:
            new = [row for row in found if row["recording_number"] not in index]
            cached = sum(1 for row in found if (county.cache / "pdf" / f"{row['recording_number']}.pdf").exists())
            print(json.dumps({"county": county.name, "from": start.isoformat(), "to": end.isoformat(),
                              "recordings": dict(Counter(row["kind"] for row in found)), "new_to_index": len(new),
                              "pdfs_cached": cached, "pdfs_to_fetch": len(found) - cached,
                              "sample": found[:3]}, indent=2))
            return 0
        for row in found:
            index[row["recording_number"]] = {**row, **{k: v for k, v in index.get(row["recording_number"], {}).items()
                                                        if k == "unavailable"}}
        save_index(county, index)
        if not manual:
            print(f"{county.name}: {len(found)} recordings {start}..{end} ({dict(Counter(r['kind'] for r in found))}); "
                  f"{len(index)} in the index", flush=True)

        engine_name = args.ocr_engine or county.settings["ocr_engine"]
        fetched = Counter()
        if args.import_folder and manual:
            imported = import_exported(county, index, args.import_folder, engine_name)
            save_index(county, index)
            fetched.update({key: value for key, value in imported.items() if key != "unrecognised"})
            print(f"  imported from {args.import_folder}: {imported}; {len(index)} in the index", flush=True)
        elif args.import_folder:
            imported = import_folder(county, index, args.import_folder, engine_name)
            fetched.update({key: value for key, value in imported.items() if key != "unmatched"})
            print(f"  imported from {args.import_folder}: {imported}", flush=True)
        if args.fetch:
            fetched.update(fetch_documents(county, index, args.assisted, args.limit))
        pdfs = sorted((county.cache / "pdf").glob("*.pdf")) if (county.cache / "pdf").exists() else []
        ocred = run_ocr(county, pdfs, engine_name, int(county.settings["ocr_workers"]))
        print(f"  documents {dict(fetched)}; OCR'd {ocred} new", flush=True)
        if args.todo:
            print(f"  {write_todo(county, index, args.todo)} documents still to save -> {args.todo}", flush=True)

        parsed = parse_all(county, index)
        foreclosures, unlinked = link(parsed["notice"], parsed["cancellation"], parsed["trustee_deed"])
        layer = ParcelLayer(county.parcels, client)
        parcels = layer.by_apn([f.notice["apn"] for f in foreclosures.values() if f.notice.get("apn")])
        checks_path = county.cache / "status_checks.json"
        checks = json.loads(checks_path.read_text()) if checks_path.exists() else {}
        records, unplaced = [], []
        for foreclosure in foreclosures.values():
            if foreclosure.deed and foreclosure.notice.get("beneficiary"):
                lines = ocr_lines(county, foreclosure.deed["recording_number"]) or []
                foreclosure.deed.update(parse_trustee_deed(lines, foreclosure.deed["recording_number"],
                                                           date.fromisoformat(foreclosure.deed["recording_date"]),
                                                           foreclosure.notice["beneficiary"], county.recorder))
            address, source, parcel = place(foreclosure, parcels, layer)
            if address is None:
                unplaced.append(foreclosure.notice["recording_number"])
                continue
            records.append(foreclosure_record(foreclosure, address, source, parcel, checks))

    records.sort(key=lambda r: (r["sale_date"] or "", r["key"]))
    snapshot = {"source_system": SOURCE_SYSTEM, "state": "AZ", "county": county.name,
                "source_url": county.recorder["website"], "scraped_at": datetime.now(timezone.utc).isoformat(),
                "parser_version": PARSER_VERSION, "foreclosures": records}
    output = args.output or output_path(county)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, indent=1) + "\n")
    summary = report(parsed, foreclosures, records, unplaced, unlinked, index, fetched)
    args.run_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (args.run_dir / f"{county.slug}-{stamp}.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({key: summary[key] for key in ("indexed", "parsed", "notice_parse_success", "by_status",
                                                     "upcoming_sales", "address_source", "with_assessor_data",
                                                     "unlinked_events", "without_address_count")}, indent=2))
    print(f"-> {output}; report {args.run_dir / f'{county.slug}-{stamp}.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
