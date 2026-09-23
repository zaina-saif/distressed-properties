"""One-shot Kings court PDF collector for use from a scheduler.

Fetches the current court calendar and each linked PDF. It never treats a
Cloudflare challenge as a successful scrape or loads filename-only data as
verified PDF content. Run from an authorized network where court PDFs work.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import uuid
from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader
from sqlalchemy import text as sql_text

from app.database.session import engine
from pipeline.load_nyc_kings_court_foreclosures import DEFAULT_INPUT, SOURCE_SYSTEM, load as load_index

DEFAULT_CACHE = Path("../.local/nyc-kings-court-pdfs")
DEFAULT_OUTPUT = DEFAULT_CACHE / "latest.json"
USER_AGENT = "nj-sheriff-sale-platform/1.0 (+court foreclosure notice collection)"
INDEX_RE = re.compile(r"\b(?:index\s*(?:no\.?|number)?|idx\.?\s*no\.?)\s*[:#]?\s*(\d{5,6}[/\-]\d{4})\b", re.I)
BLOCK_RE = re.compile(r"\bblock\s*(?:no\.?|number)?\s*[:#]?\s*0*(\d{1,5})\b", re.I)
LOT_RE = re.compile(r"\blot\s*(?:no\.?|number)?\s*[:#]?\s*0*(\d{1,4})\b", re.I)
PARTY_RE = {
    "plaintiff": re.compile(r"(?im)^\s*plaintiff(?:s)?\s*[:\-]\s*([^\n]{3,160})"),
    "defendant": re.compile(r"(?im)^\s*defendant(?:s)?\s*[:\-]\s*([^\n]{3,160})"),
}
JUDGMENT_RE = re.compile(r"approximate\s+amount\s+of\s+judgment\s+is\s*\$\s*([\d,]+(?:\.\d{2})?)", re.I)
NOTICE_DATE_RE = re.compile(
    r"(?:sell\s+at\s+public\s+auction|public\s+auction)[\s\S]{0,200}?\bon\s+"
    r"([A-Z][a-z]+\s+\d{1,2},?\s+\d{4})\s+at\b", re.I)


class CourtAccessBlocked(RuntimeError):
    """The court returned an access challenge; no import should proceed."""


def checked_get(client: httpx.Client, url: str) -> httpx.Response:
    response = client.get(url)
    html_challenge = ("text/html" in response.headers.get("content-type", "")
                      and "Just a moment" in response.text[:500])
    if response.status_code in (403, 429) or html_challenge:
        raise CourtAccessBlocked(f"Court access challenge ({response.status_code}) at {url}")
    response.raise_for_status()
    return response


def parse_calendar_date(html: str) -> str:
    page_text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    match = re.search(r"next scheduled auction date will be\s+([A-Z][a-z]+\s+\d{1,2},\s+\d{4})", page_text, re.I)
    if not match:
        raise ValueError("Court page has no explicit next auction date")
    return datetime.strptime(match.group(1), "%B %d, %Y").date().isoformat()


def parse_pdf_links(html: str, directory_url: str) -> list[dict[str, str]]:
    directory = urlparse(directory_url)
    links = []
    seen = set()
    for anchor in BeautifulSoup(html, "html.parser").find_all("a", href=True):
        href = anchor["href"]
        if not href.lower().endswith(".pdf"):
            continue
        url = urljoin(directory_url, href)
        parsed = urlparse(url)
        if parsed.netloc.lower() != directory.netloc.lower() or not parsed.path.startswith(directory.path):
            raise ValueError(f"PDF link leaves court directory: {url}")
        filename = unquote(Path(parsed.path).name)
        if filename in seen:
            continue
        seen.add(filename)
        links.append({"filename": filename, "source_url": url})
    if not links:
        raise ValueError("Court directory has no PDF links")
    return links


def extract_pdf_text(data: bytes, path: Path, *, ocr: bool = True) -> tuple[str, str]:
    if not data.startswith(b"%PDF-"):
        raise ValueError("Court response is not a PDF")
    reader = PdfReader(BytesIO(data))
    text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    if len(text) >= 80:
        return text, "embedded_text"
    if not ocr:
        return text, "no_extractable_text"
    script = Path(__file__).with_name("ocr_pdf_macos.swift")
    module_cache = path.parent / "swift-module-cache"
    module_cache.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["CLANG_MODULE_CACHE_PATH"] = str(module_cache.resolve())
    environment["SWIFT_MODULE_CACHE_PATH"] = str(module_cache.resolve())
    executable = path.parent / "ocr_pdf_macos"
    if not executable.exists() or executable.stat().st_mtime < script.stat().st_mtime:
        subprocess.run(["swiftc", str(script), "-o", str(executable)],
                       capture_output=True, text=True, timeout=180,
                       check=True, env=environment)
    result = subprocess.run([str(executable), str(path)], capture_output=True,
                            text=True, timeout=180, check=True, env=environment)
    text = result.stdout.strip()
    return text, "macos_vision_ocr" if text else "no_extractable_text"


def parse_notice(text: str) -> dict:
    indexes = set(INDEX_RE.findall(text))
    blocks = set(BLOCK_RE.findall(text))
    lots = set(LOT_RE.findall(text))
    judgment = JUDGMENT_RE.search(text)
    notice_date = NOTICE_DATE_RE.search(text)
    result = {
        "court_case_number": next(iter(indexes)) if len(indexes) == 1 else None,
        "block": next(iter(blocks)) if len(blocks) == 1 else None,
        "lot": next(iter(lots)) if len(lots) == 1 else None,
        "bbl": None,
        "judgment_amount": judgment.group(1).replace(",", "") if judgment else None,
        "notice_sale_date": None,
        "plaintiff": None,
        "defendant": None,
    }
    if notice_date:
        raw_date = re.sub(r"\s+", " ", notice_date.group(1).replace(",", " ")).strip()
        result["notice_sale_date"] = datetime.strptime(raw_date, "%B %d %Y").date().isoformat()
    if result["block"] and result["lot"]:
        result["bbl"] = "3" + result["block"].zfill(5) + result["lot"].zfill(4)
    for field, pattern in PARTY_RE.items():
        match = pattern.search(text)
        if match:
            result[field] = match.group(1).strip(" ,.;")
    return result


def collect(snapshot_path: Path = DEFAULT_INPUT, output_path: Path = DEFAULT_OUTPUT,
            cache_dir: Path = DEFAULT_CACHE, *, ocr: bool = True) -> dict:
    snapshot = json.loads(snapshot_path.read_text())
    page_url = snapshot["source_page_url"]
    directory_url = snapshot["source_directory_url"]
    with httpx.Client(timeout=45, follow_redirects=True,
                      headers={"User-Agent": USER_AGENT}) as client:
        sale_date = parse_calendar_date(checked_get(client, page_url).text)
        links = parse_pdf_links(checked_get(client, directory_url).text, directory_url)
        cache_dir.mkdir(parents=True, exist_ok=True)
        records = []
        for link in links:
            response = checked_get(client, link["source_url"])
            data = response.content
            if not data.startswith(b"%PDF-"):
                raise ValueError(f"Not a PDF: {link['source_url']}")
            digest = hashlib.sha256(data).hexdigest()
            pdf_path = cache_dir / f"{digest}.pdf"
            if not pdf_path.exists():
                pdf_path.write_bytes(data)
            text, method = extract_pdf_text(data, pdf_path, ocr=ocr)
            fields = parse_notice(text)
            parse_status = "parsed" if text else "unreadable"
            if fields["notice_sale_date"] and fields["notice_sale_date"] != sale_date:
                parse_status = "date_mismatch_review_required"
            records.append({**link, "sale_date": sale_date, "pdf_sha256": digest,
                            "extraction_method": method, "pdf_text": text,
                            "fields": fields, "parse_status": parse_status})
    result = {"source_page_url": page_url, "source_directory_url": directory_url,
              "checked_at": datetime.now().astimezone().isoformat(),
              "sale_date": sale_date, "records": records}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n")
    return {"sale_date": sale_date, "pdfs": len(records),
            "readable": sum(bool(record["pdf_text"]) for record in records),
            "output": str(output_path)}


def import_collected(path: Path, cache_dir: Path = DEFAULT_CACHE,
                     snapshot_path: Path = DEFAULT_INPUT) -> dict:
    result = json.loads(path.read_text())
    records = result["records"]
    if not records or any(not record["pdf_sha256"] for record in records):
        raise ValueError("Cannot load an incomplete PDF collection")
    snapshot = json.loads(snapshot_path.read_text())
    snapshot.update({"sale_date": result["sale_date"],
                     "source_checked_date": date.fromisoformat(result["checked_at"][:10]).isoformat(),
                     "notice_filenames": [record["filename"] for record in records]})
    current_index = cache_dir / "current_index.json"
    current_index.parent.mkdir(parents=True, exist_ok=True)
    current_index.write_text(json.dumps(snapshot, indent=2) + "\n")
    index_result = load_index(current_index)
    run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    enriched = 0
    with engine.begin() as connection:
        connection.execute(sql_text("""INSERT INTO scrape_runs
            (id,job_name,county,source_system,started_at,status,records_found)
            VALUES(:id,'nyc_kings_court_pdf_enrichment','Kings',:source,:now,'running',:count)"""),
            {"id": run_id, "source": SOURCE_SYSTEM, "now": now, "count": len(records)})
        for record in records:
            fields = record["fields"]
            source_url = record["source_url"]
            sale_id = connection.execute(sql_text("""SELECT id FROM sheriff_sales
                WHERE source_system=:source AND source_url=:url
                  AND current_sale_date::date=:sale_date"""),
                {"source": SOURCE_SYSTEM, "url": source_url,
                 "sale_date": result["sale_date"]}).scalar()
            if sale_id is None:
                raise ValueError(f"No matching indexed court listing: {source_url}")
            payload = json.dumps(record, sort_keys=True)
            content_hash = hashlib.sha256(payload.encode()).hexdigest()
            connection.execute(sql_text("""INSERT INTO raw_scrape_records
                (id,scrape_run_id,state,county,source_record_id,source_url,raw_payload,
                 content_hash,parsing_status,scraped_at)
                VALUES(:id,:run,'NY','Kings',:record_id,:url,CAST(:payload AS JSONB),
                       :hash,:status,:now) ON CONFLICT DO NOTHING"""),
                {"id": str(uuid.uuid4()), "run": run_id, "record_id": record["filename"],
                 "url": source_url, "payload": payload, "hash": content_hash,
                 "status": record["parse_status"], "now": now})
            if record["parse_status"] != "parsed":
                continue
            connection.execute(sql_text("""UPDATE sheriff_sales SET
                court_case_number=COALESCE(:case_number,court_case_number),
                property_number=COALESCE(:bbl,property_number),
                judgment_amount=COALESCE(:judgment_amount,judgment_amount),
                plaintiff=COALESCE(:plaintiff,plaintiff),
                defendant=COALESCE(:defendant,defendant),
                updated_at=NOW() WHERE id=:id"""),
                {"id": sale_id, "case_number": fields.get("court_case_number"),
                 "bbl": fields.get("bbl"), "plaintiff": fields.get("plaintiff"),
                 "defendant": fields.get("defendant"),
                 "judgment_amount": fields.get("judgment_amount")})
            enriched += 1
        connection.execute(sql_text("""UPDATE sheriff_sales SET
            current_status='removed_from_court_index_unverified',is_active=FALSE,
            updated_at=NOW()
            WHERE source_system=:source AND state='NY' AND county='Kings'
              AND current_status='scheduled_unverified'
              AND (current_sale_date::date<>:sale_date
                   OR NOT (source_url = ANY(:current_urls)))"""),
            {"source": SOURCE_SYSTEM,
             "sale_date": result["sale_date"],
             "current_urls": [record["source_url"] for record in records]})
        connection.execute(sql_text("""UPDATE scrape_runs SET completed_at=NOW(),status='completed',
            records_updated=:updated WHERE id=:id"""),
            {"updated": enriched, "id": run_id})
    return {"indexed": index_result, "pdfs_enriched": enriched}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--no-ocr", action="store_true")
    parser.add_argument("--load", action="store_true",
                        help="After a complete download, upsert listings and verified PDF fields")
    args = parser.parse_args()
    try:
        collected = collect(args.snapshot, args.output, args.cache_dir,
                            ocr=not args.no_ocr)
        if args.load:
            collected["database"] = import_collected(args.output, args.cache_dir, args.snapshot)
        print(json.dumps(collected))
    except CourtAccessBlocked as exc:
        parser.exit(2, f"blocked: {exc}\n")


if __name__ == "__main__":
    main()
