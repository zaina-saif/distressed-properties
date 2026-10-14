"""Load NY Supreme Court foreclosure-auction PDFs that the operator saved by hand.

The court sites block scripts (Cloudflare), so the operator opens them in a
normal browser and saves the PDFs into one folder. This reads every PDF there
(OCR for scans), parses it (pipeline.parse_ny_court_pdfs) and loads referee
auctions through sale_listing_loader, keyed by court index number, so a rerun
updates listings instead of duplicating them.

    python -m pipeline.load_ny_court_pdfs --folder ~/Documents/SheriffSaleProject/Files_For_NY --dry-run
    python -m pipeline.load_ny_court_pdfs --folder ~/Documents/SheriffSaleProject/Files_For_NY

A record that fails validation is written to <run-dir>/ny_court_parse_failures.json
and never loaded. The Manhattan Foreclosure Auction Part list has no addresses,
so its cases are reported, not loaded. A WebCivil Appearance Detail page saved for
a case adds that case's earlier auction dates and outcomes to its listing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import uuid
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

from pypdf import PdfReader
from sqlalchemy import text

from app.database.session import engine
from pipeline.collect_nyc_kings_foreclosure_pdfs import macos_ocr
from pipeline.load_nyc_referee_sales import merge_court_duplicates
from pipeline.parse_ny_court_pdfs import (
    kind, parse_auction_part_list, parse_calendar_summary, parse_notice_of_sale, parse_webcivil_appearances,
)
from pipeline.sale_listing_loader import Sale, load_sales

SOURCE_SYSTEM = "ny_court_foreclosure_auction"
PARSER_VERSION = "ny_court_pdfs_v1"
CACHE = Path("../.local/ny-court-pdfs")
BOROUGH_CODE = {"New York": "1", "Bronx": "2", "Kings": "3", "Queens": "4", "Richmond": "5"}
SOURCE_URLS = {
    "Kings": "https://www.nycourts.gov/courts/2nd-judicial-district/kings-county-supreme-court-civil-term/foreclosure-sales",
    "Bronx": "https://nycourts.gov/LegacyPDFS/courts/12jd/bronx/civil/pdfs/foreclosure-auctions.pdf",
    "New York": "https://www.nycourts.gov/courts/1jd/supctmanh/foreclosures.shtml",
}
WEBCIVIL_URL = "https://iapps.courts.state.ny.us/webcivil/FCASMain"
# WebCivil auction outcomes as listing statuses.
OUTCOME_STATUS = {"Not Held": "adjourned", "Adjourned": "adjourned", "Sold": "sold", "Cancelled": "cancelled",
                  "Canceled": "cancelled", "Stayed": "stayed", "Marked Off": "cancelled", "Withdrawn": "cancelled",
                  "Vacated": "cancelled", "Released": "cancelled"}
CALENDAR_NOTE = re.compile(r"\s*Court calendar \(WebCivil\):.*$", re.S)
# Streets OCR misread, corrected by hand and keyed by index number so every rerun keeps them.
STREET_CORRECTIONS = {
    "804535/2024": "2065 Turnbull Avenue",  # OCR read "Tumbul Avenue" (Bronx calendar)
    "705527/2014": "133-44 122nd Street",  # broken over a line; both text layers lose "133-44" (Queens notice)
}
# Plaintiffs OCR misread, the same way.
PLAINTIFF_CORRECTIONS = {
    "705527/2014": "NATIONSTAR MORTGAGE LLC",  # OCR read "LIC"
}


def ocr_text(document: dict) -> str | None:
    """Vision OCR of a saved PDF whose embedded text layer is itself a poor OCR ("1011612026"), cached."""
    if not document.get("pdf"):
        return None
    cached = CACHE / "text" / f"{document['sha256'][:16]}-ocr.json"
    if cached.exists():
        return json.loads(cached.read_text())["text"]
    body = macos_ocr(Path(document["pdf"]), timeout=900)
    cached.write_text(json.dumps({"text": body, "method": "macos_vision_ocr"}))
    return body


def pdf_text(path: Path) -> tuple[str, str]:
    """Embedded text, or OCR when most pages are scans (the Bronx list has text on its cover only)."""
    reader = PdfReader(path)
    embedded = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    if len(embedded) >= 400 * len(reader.pages):
        return embedded, "embedded_text"
    ocr = macos_ocr(path, timeout=900)
    return (ocr, "macos_vision_ocr") if len(ocr) > len(embedded) else (embedded, "embedded_text")


def county_of(document_text: str) -> str | None:
    body = " ".join(document_text.split())
    for pattern, county in ((r"KINGS COUNTY CLERK|COUNTY OF KINGS|Kings County Supreme", "Kings"),
                            (r"County:\s*Bronx|Bronx \(Supreme\)|TWELFTH JUDICIAL DISTRICT", "Bronx"),
                            (r"QUEENS COUNTY CLERK|COUNTY OF QUEENS", "Queens"),
                            (r"RICHMOND COUNTY CLERK|COUNTY OF RICHMOND", "Richmond"),
                            (r"FORECLOSURE AUCTION PART|NEW YORK COUNTY CLERK|COUNTY OF NEW YORK", "New York")):
        if re.search(pattern, body, re.I):
            return county
    return None


def bbl(county: str, block: str | None, lot: str | None) -> str | None:
    if not (block and lot and county in BOROUGH_CODE):
        return None
    return f"{BOROUGH_CODE[county]}-{int(block):05d}-{int(lot):04d}"


def read_folder(folder: Path) -> list[dict]:
    """One entry per distinct PDF (by content), with cached text."""
    (CACHE / "files").mkdir(parents=True, exist_ok=True)
    (CACHE / "text").mkdir(parents=True, exist_ok=True)
    documents, seen = [], set()
    for path in sorted(folder.glob("*.pdf")):
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest in seen or not data.startswith(b"%PDF-"):
            continue
        seen.add(digest)
        copy = CACHE / "files" / f"{digest[:16]}.pdf"
        if not copy.exists():
            shutil.copyfile(path, copy)
        cached = CACHE / "text" / f"{digest[:16]}.json"
        if cached.exists():
            extracted = json.loads(cached.read_text())
        else:
            body, method = pdf_text(copy)
            extracted = {"text": body, "method": method}
            cached.write_text(json.dumps(extracted))
        # Kings names each notice file after the property ("644 LORIMER STREET #6.pdf").
        name = re.sub(r"\s*\(\d+\)$", "", path.stem)
        documents.append({"file": path.name, "sha256": digest, "file_address": name, "pdf": str(copy), **extracted})
    return documents


def parse_documents(documents: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Returns loadable records, failures and reported-only (no address) records."""
    records, failures, reported = [], [], []
    for document in documents:
        source = {"file": document["file"], "sha256": document["sha256"], "text_method": document["method"]}
        layout, county = kind(document["text"]), county_of(document["text"])
        if layout.startswith("webcivil_"):
            continue  # case pages, read by parse_appearances
        if not county:
            failures.append({**source, "problems": ["county_not_recognised"], "layout": layout})
            continue
        if layout == "notice_of_sale":
            parsed = [parse_notice_of_sale(document["text"], county, document["file_address"])]
            if parsed[0][1] and document["method"] == "embedded_text" and (ocr := ocr_text(document)):
                retry = parse_notice_of_sale(ocr, county, document["file_address"])
                if not retry[1]:
                    parsed, source = [retry], {**source, "text_method": "macos_vision_ocr_fallback"}
        elif layout == "calendar_summary":
            parsed = parse_calendar_summary(document["text"], county)
        elif layout == "auction_part_list":
            reported.extend({**record, **source} for record, _ in parse_auction_part_list(document["text"], county))
            continue
        else:
            failures.append({**source, "problems": ["layout_not_recognised"], "county": county})
            continue
        for record, problems in parsed:
            entry = {**record, **source}
            if problems or not record.get("index_number") or not record.get("sale_date"):
                failures.append({**entry, "problems": problems or ["index_or_date_missing"]})
            else:
                if entry["index_number"] in STREET_CORRECTIONS:
                    entry.update(street=STREET_CORRECTIONS[entry["index_number"]], address_source="manual_correction")
                if entry["index_number"] in PLAINTIFF_CORRECTIONS:
                    entry.update(plaintiff=PLAINTIFF_CORRECTIONS[entry["index_number"]])
                records.append(entry)
    return records, failures, reported


def parse_appearances(documents: list[dict]) -> tuple[list[dict], list[dict]]:
    """Auction histories from WebCivil Appearance Detail pages, and the pages that failed."""
    histories, failures = [], []
    for document in documents:
        if kind(document["text"]) != "webcivil_appearances":
            continue
        record, problems = parse_webcivil_appearances(document["text"])
        entry = {**record, "file": document["file"], "sha256": document["sha256"]}
        (failures if problems else histories).append({**entry, "problems": problems} if problems else entry)
    return histories, failures


def calendar_note(auctions: list[dict], today: date) -> str | None:
    """One sentence on a case's earlier auction dates, for the notice details."""
    past = sorted((a for a in auctions if a["outcome"] and a["date"] < today.isoformat()), key=lambda a: a["date"])
    if not past:
        return None
    not_held = [a["date"] for a in past if a["outcome"] == "Not Held"]
    parts = []
    if not_held:
        parts.append(f"{len(not_held)} earlier auction date{'s' if len(not_held) > 1 else ''} not held "
                     f"({', '.join(not_held)})")
    for auction in past:
        if auction["outcome"] == "Not Held":
            continue
        phrase = f"the {auction['date']} auction is recorded as {auction['outcome'].lower()}"
        if auction["outcome"] == "Sold" and any(a["date"] > auction["date"] for a in auctions):
            phrase += ", and the case was put back on the auction calendar afterwards"
        parts.append(phrase)
    return f"Court calendar (WebCivil): {'; '.join(parts)}."


def apply_appearances(histories: list[dict], today: date) -> dict[str, int]:
    """Adds each past auction appearance to the matching listing's status history, updates the
    listing when its own auction date has an outcome, and notes the history in its details."""
    counts = Counter()
    with engine.begin() as connection:
        for history in histories:
            sales = connection.execute(text("""SELECT id, current_sale_date::date AS sale_date, current_status,
                description_text FROM sheriff_sales WHERE state='NY' AND county=:county AND sheriff_number=:index"""),
                {"county": history["county"], "index": history["index_number"]}).mappings().all()
            if not sales:
                counts["cases_without_listing"] += 1
                continue
            for sale in sales:
                for auction in history["auctions"]:
                    status = OUTCOME_STATUS.get(auction["outcome"])
                    if not status or auction["date"] >= today.isoformat():
                        continue
                    raw = f"Auction {'held: sold' if status == 'sold' else auction['outcome'].lower()} (WebCivil)"
                    counts["history_added"] += connection.execute(text("""INSERT INTO sheriff_sale_status_history
                        (id,sheriff_sale_id,status,sale_date,observed_at,source_url,raw_status)
                        SELECT :hid,:id,:status,:sale_date,NOW(),:url,:raw WHERE NOT EXISTS(
                          SELECT 1 FROM sheriff_sale_status_history WHERE sheriff_sale_id=:id AND status=:status
                            AND sale_date::date = CAST(:sale_date AS DATE))"""),
                        {"hid": str(uuid.uuid4()), "id": sale["id"], "status": status, "sale_date": auction["date"],
                         "url": WEBCIVIL_URL, "raw": raw}).rowcount
                    if sale["sale_date"] and auction["date"] == sale["sale_date"].isoformat() \
                            and sale["current_status"] in ("scheduled", "scheduled_unverified", "sold_or_cancelled_unverified"):
                        connection.execute(text("""UPDATE sheriff_sales SET current_status=:status, updated_at=NOW()
                            WHERE id=:id"""), {"status": status, "id": sale["id"]})
                        counts["listings_updated"] += 1
                note = calendar_note(history["auctions"], today)
                described = CALENDAR_NOTE.sub("", sale["description_text"] or "").strip()
                connection.execute(text("""UPDATE sheriff_sales SET description_text=:details, updated_at=NOW()
                    WHERE id=:id"""), {"details": " ".join(filter(None, [described, note])) or None, "id": sale["id"]})
    return dict(counts)


def details(record: dict) -> str:
    parts = ["Court-ordered referee foreclosure auction."]
    when = " ".join(filter(None, [record.get("sale_date"), record.get("sale_time")]))
    if record.get("sale_place"):
        when += f" at {record['sale_place']}"
    parts.append(f"Auction: {when}.")
    if record.get("referee"):
        parts.append(f"Referee: {record['referee']}.")
    if record.get("judgment"):
        parts.append(f"Approximate judgment: ${record['judgment']:,.2f} plus interest and costs (the minimum bid is "
                     "set by the plaintiff at the sale; the judgment is an estimate of it).")
    if record.get("approximate_lien_amount"):
        parts.append(f"Notice states an approximate lien amount of ${record['approximate_lien_amount']:,.2f} plus interest and costs; "
                     "this is not treated as a verified judgment or unpaid principal balance.")
    if record.get("block") and record.get("lot"):
        parts.append(f"Block {record['block']}, Lot {record['lot']}.")
    if record.get("plaintiff_attorney"):
        parts.append(f"Plaintiff's attorney: {record['plaintiff_attorney']}.")
    if record.get("postponed_from"):
        parts.append(f"Postponed from {record['postponed_from']}.")
    parts.append(f"Index No. {record['index_number']} (look up filings on NYSCEF). Winning bidders typically "
                 "pay a 10% deposit at the auction.")
    return " ".join(parts)


def to_sales(records: list[dict], today: date) -> dict[str, list[Sale]]:
    """Per county, oldest first, so each case's status history ends with its latest date."""
    by_county: dict[str, list[Sale]] = {}
    for record in records:
        when = date.fromisoformat(record["sale_date"])
        common = dict(case=record["index_number"], street=record["street"], city=record["city"],
                      zip_code=record.get("zip_code"), raw={**record, "parser_version": PARSER_VERSION},
                      parcel=(f"Block {record['block']} Lot {record['lot']}" if record.get("block") else None),
                      judgment=record.get("judgment"), plaintiff=record.get("plaintiff"),
                      attorney=record.get("plaintiff_attorney"), property_number=bbl(
                          record["county"], record.get("block"), record.get("lot")))
        sales = by_county.setdefault(record["county"], [])
        if record.get("postponed_from"):
            earlier = date.fromisoformat(record["postponed_from"])
            sales.append(Sale(**common, sale_date=earlier, status="adjourned",
                              raw_status=f"Postponed to {record['sale_date']}"))
        status = "scheduled" if when >= today else "sold_or_cancelled_unverified"
        sales.append(Sale(**common, sale_date=when, status=status,
                          raw_status="Referee auction scheduled" if status == "scheduled"
                          else "Auction date passed; result not published"))
    for sales in by_county.values():
        sales.sort(key=lambda sale: sale.sale_date)
    return by_county


def apply_details(records: list[dict]) -> None:
    latest = {}
    for record in sorted(records, key=lambda r: r["sale_date"]):
        latest[(record["county"], record["index_number"])] = record
    with engine.begin() as connection:
        for (county, index), record in latest.items():
            # Keeps a WebCivil calendar note added by an earlier run (apply_appearances).
            connection.execute(text("""UPDATE sheriff_sales SET description_text=:details
                || COALESCE(' ' || substring(description_text from ' (Court calendar \\(WebCivil\\):.*)$'), ''),
                updated_at=NOW()
                WHERE state='NY' AND county=:county AND source_system=:source AND sheriff_number=:index"""),
                {"details": details(record), "county": county, "source": SOURCE_SYSTEM, "index": index})


def supersede_old_kings_index(records: list[dict]) -> int:
    """The older Kings source (nyc_kings_court_foreclosure_index) listed addresses only;
    when a notice now covers the same house, that row becomes an adjourned past date."""
    streets = {record["street"].upper() for record in records if record["county"] == "Kings"}
    changed = 0
    with engine.begin() as connection:
        rows = connection.execute(text("""SELECT ss.id, upper(p.street_address) FROM sheriff_sales ss
            JOIN properties p ON p.id=ss.property_id WHERE ss.source_system='nyc_kings_court_foreclosure_index'
            AND ss.current_status='scheduled_unverified'""")).all()
        for sale_id, street in rows:
            if street in streets:
                connection.execute(text("""UPDATE sheriff_sales SET current_status='adjourned', updated_at=NOW()
                    WHERE id=:id"""), {"id": sale_id})
                connection.execute(text("""INSERT INTO sheriff_sale_status_history(id,sheriff_sale_id,status,
                    observed_at,raw_status) VALUES(:hid,:id,'adjourned',NOW(),
                    'Rescheduled; see the court Notice of Sale listing for this property')"""),
                    {"hid": str(uuid.uuid4()), "id": sale_id})
                changed += 1
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--folder", type=Path, required=True, help="Folder of PDFs saved from the court sites")
    parser.add_argument("--run-dir", type=Path, default=CACHE / "runs" / datetime.now().strftime("%Y%m%d-%H%M%S"))
    parser.add_argument("--dry-run", action="store_true", help="Parse and report; write nothing to the database")
    args = parser.parse_args()
    documents = read_folder(args.folder.expanduser())
    records, failures, reported = parse_documents(documents)
    histories, history_failures = parse_appearances(documents)
    failures += history_failures
    args.run_dir.mkdir(parents=True, exist_ok=True)
    (args.run_dir / "ny_court_parse_failures.json").write_text(json.dumps(failures, indent=1, default=str))
    (args.run_dir / "ny_court_records.json").write_text(json.dumps(records, indent=1, default=str))
    (args.run_dir / "ny_court_reported_only.json").write_text(json.dumps(reported, indent=1, default=str))
    (args.run_dir / "ny_court_webcivil_histories.json").write_text(json.dumps(histories, indent=1, default=str))
    indexes = {(r["county"], r["index_number"]) for r in records}
    summary = {
        "pdfs": len(documents), "records": len(records), "distinct_cases": len(indexes),
        "by_county": dict(Counter(r["county"] for r in records)),
        "with_judgment": sum(1 for r in records if r.get("judgment")),
        "with_block_lot": sum(1 for r in records if r.get("block")),
        "upcoming": sum(1 for r in records if r["sale_date"] >= date.today().isoformat()),
        "failures": len(failures), "reported_without_address": len(reported),
        "webcivil_case_histories": len(histories), "run_dir": str(args.run_dir),
    }
    print(json.dumps(summary, indent=1))
    if args.dry_run:
        for record in records[:10]:
            print(json.dumps({k: record.get(k) for k in ("county", "index_number", "sale_date", "street", "city",
                                                          "zip_code", "block", "lot", "judgment", "referee")}))
        for history in histories:
            print(json.dumps({k: history[k] for k in ("county", "index_number", "auctions")}))
        return
    now = datetime.now(timezone.utc)
    for county, sales in to_sales(records, date.today()).items():
        result = load_sales("NY", county, SOURCE_SYSTEM, SOURCE_URLS.get(county, SOURCE_URLS["Kings"]), sales,
                            job=f"ny_court_pdfs_{county.lower().replace(' ', '_')}", complete=False)
        print(f"NY {county}: {result}", flush=True)
    apply_details(records)
    print(f"WebCivil auction histories: {apply_appearances(histories, date.today())}")
    print(f"Older Kings index rows marked adjourned: {supersede_old_kings_index(records)}")
    with engine.begin() as connection:
        print(f"NYCTL tax-lien listings merged into court listings: {merge_court_duplicates(connection)}")
    print(f"Loaded at {now.isoformat()}")


if __name__ == "__main__":
    main()
