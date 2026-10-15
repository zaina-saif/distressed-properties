"""Text of a saved court PDF, page by page: the embedded text layer, or macOS Vision OCR
for scanned pages. Results are cached by file hash in data/cache/text/.

Scanned NYSCEF filings (older summonses) carry only the clerk's "FILED:" stamp as text,
so a page with little text is OCR'd. Only the first OCR_PAGES pages are OCR'd: the
summons, complaint and their exhibits that matter come first, and a filing can run
to 130 pages.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

import pdfplumber
from pypdf import PdfReader, PdfWriter

from db import DATA

CACHE = DATA / "cache"
OCR_SCRIPT = Path(__file__).resolve().parents[1] / "backend/pipeline/ocr_pdf_macos.swift"
OCR_PAGES = 25
MIN_PAGE_CHARS = 200  # a page with less embedded text than this is treated as a scan
PAGE_BREAK = "\f"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ocr_binary() -> Path:
    binary = CACHE / "bin" / "ocr_pdf_macos"
    if not binary.exists() or binary.stat().st_mtime < OCR_SCRIPT.stat().st_mtime:
        binary.parent.mkdir(parents=True, exist_ok=True)
        module_cache = CACHE / "bin" / "swift-module-cache"
        environment = {**os.environ, "CLANG_MODULE_CACHE_PATH": str(module_cache),
                       "SWIFT_MODULE_CACHE_PATH": str(module_cache)}
        subprocess.run(["swiftc", str(OCR_SCRIPT), "-o", str(binary)], check=True, capture_output=True,
                       text=True, timeout=300, env=environment)
    return binary


def ocr_page(path: Path, page_number: int) -> str:
    """Vision OCR of one page (0-based)."""
    with tempfile.TemporaryDirectory() as folder:
        single = Path(folder) / "page.pdf"
        writer = PdfWriter()
        writer.add_page(PdfReader(path).pages[page_number])
        with single.open("wb") as handle:
            writer.write(handle)
        result = subprocess.run([str(_ocr_binary()), str(single)], capture_output=True, text=True,
                                timeout=180, check=True)
    return result.stdout.strip()


def page_texts(path: Path, ocr: bool = True) -> tuple[list[str], str]:
    """(text of each page, method). Method is 'embedded_text' or 'macos_vision_ocr' when any page was OCR'd."""
    digest = sha256_file(path)
    cached = CACHE / "text" / f"{digest[:20]}.json"
    if cached.exists():
        data = json.loads(cached.read_text())
        if data["method"] == "embedded_text" or ocr:
            return data["pages"], data["method"]
    with pdfplumber.open(path) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    method = "embedded_text"
    if ocr:
        for number, text in enumerate(pages[:OCR_PAGES]):
            # The clerk's stamp ("FILED: QUEENS COUNTY CLERK ... RECEIVED NYSCEF") is ~110 characters.
            if len(text.strip()) < MIN_PAGE_CHARS:
                recognized = ocr_page(path, number)
                if len(recognized) > len(text.strip()):
                    pages[number], method = recognized, "macos_vision_ocr"
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps({"file": path.name, "method": method, "pages": pages}))
    return pages, method
