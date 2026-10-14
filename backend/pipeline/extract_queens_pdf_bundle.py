"""Extract one Queens WebCivil case bundle (notice, case detail, appearances) to JSON.

This is an offline extractor for PDFs saved by the operator. It preserves source
text and document references and does not write to the database.

    python -m pipeline.extract_queens_pdf_bundle --folder ".../Queens "
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

from pypdf import PdfReader


INDEX = re.compile(r"(?<!\d)(\d{3,6})\s*/\s*((?:19|20)\d{2})")
APPEARANCE_DATE = re.compile(r"(?m)^\s*(\d{2}/\d{2}/20\d{2})(?:\s+([^\n]+))?")


def read_pdf(path: Path) -> tuple[str, str]:
    body = path.read_bytes()
    if not body.startswith(b"%PDF-"):
        raise ValueError(f"Not a PDF: {path.name}")
    text = "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    return text, hashlib.sha256(body).hexdigest()


def field(text: str, label: str) -> str | None:
    match = re.search(rf"(?m)^\s*{re.escape(label)}\s*:?\s*(.*?)\s*$", text, re.I)
    return match.group(1).strip() if match and match.group(1).strip() else None


def section(text: str, start: str, end: str) -> str:
    match = re.search(rf"{re.escape(start)}\s*:?(.*?){re.escape(end)}\s*:?", text, re.I | re.S)
    return match.group(1).strip() if match else ""


def active_attorney(text: str, start: str, end: str) -> str | None:
    block = section(text, start, end)
    for line in block.splitlines():
        match = re.search(r"^\s*(.+?)\s+Attorney Type:\s*RETAINED\s+Atty\.\s*Status:\s*Active\b", line, re.I)
        if match:
            return match.group(1).strip()
    return None


def parse_case_detail(text: str) -> dict:
    return {
        "court": field(text, "Court"),
        "index_number": (lambda m: f"{int(m.group(1))}/{m.group(2)}" if m else None)(INDEX.search(field(text, "Index Number") or "")),
        "cms_index_number": field(text, "CMS Index Number"),
        "case_caption": field(text, "Case Name"),
        "case_type": field(text, "Case Type"),
        "track": field(text, "Track"),
        "rji_filed": field(text, "RJI Filed"),
        "disposition_date": field(text, "Disposition Date"),
        "assigned_justice": field(text, "Justice Name"),
        "plaintiff": section(text, "Plaintiff/Petitioner", "Defendant/Respondent").splitlines()[0].strip() or None,
        "defendant": section(text, "Defendant/Respondent", "Attorney/Firm For Plaintiff").splitlines()[0].strip() or None,
        "plaintiff_attorney": active_attorney(text, "Attorney/Firm For Plaintiff", "Attorney/Firm For Defendant"),
        "defendant_attorney": active_attorney(text, "Attorney/Firm For Defendant", "Close"),
    }


def parse_appearances(text: str) -> list[dict]:
    if "Appearance Information:" not in text:
        return []
    body = text.split("Appearance Information:", 1)[1].split("Close", 1)[0]
    starts = list(APPEARANCE_DATE.finditer(body))
    rows = []
    for index, match in enumerate(starts):
        raw = re.sub(r"\s+", " ", body[match.start():starts[index + 1].start() if index + 1 < len(starts) else len(body)]).strip()
        try:
            date_value = datetime.strptime(match.group(1), "%m/%d/%Y").date().isoformat()
        except ValueError:
            continue
        time_match = re.match(r"(\d{1,2}:\d{2}\s+[AP]M)\b", match.group(2) or "", re.I)
        purpose_match = re.search(r"\d{4}\s*(?:\d{1,2}:\d{2}\s+[AP]M)?\s*(.+?)(?=\s+No\s|$)", raw, re.I)
        purpose = purpose_match.group(1).strip() if purpose_match else None
        outcome_match = re.search(
            r"\b(Fully Submitted\s*-\s*No Opposition|Trial Loan Modification|Not Held|Adjourned|Rescheduled|Granted|Denied|Continued|Completed|Sold|Default|Held|Decided)\b",
            raw, re.I,
        )
        part_match = re.search(
            r"\b(FORECLOSURE\s+(?:AUCTION|CONFERENCE|AO\s+CONF)\s+PART|PART\s+\d+\s+MOTIONS(?:-GUARDIANSHIP)?|"
            r"CENTRALIZED\s+MOTION\s+PART|STATUS\s+CONFERENCE\s+PT\.\s*[A-Z]|EXPARTE)\b",
            raw, re.I,
        )
        justice_match = (
            re.search(r"\b([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){0,1},\s*Hon\.\s*[A-Z][a-z][A-Za-z.'-]*(?:\s+[A-Z]\.)?)", raw)
            or re.search(r"\b([A-Z][A-Za-z.'-]+\s+Esq\.,\s*[A-Z][a-z][A-Za-z.'-]*(?:\s+[A-Z]\.)?)", raw)
            or re.search(r"\b([A-Z][A-Za-z.'-]+,\s*[A-Z][a-z][A-Za-z.'-]*(?:\s+[A-Z]\.)?)", raw)
        )
        rows.append({
            "date": date_value,
            "time": time_match.group(1) if time_match else None,
            "part": part_match.group(1).strip() if part_match else None,
            "purpose": purpose,
            "outcome": outcome_match.group(1).strip() if outcome_match else None,
            "justice": justice_match.group(1).strip() if justice_match else None,
            "raw_text": raw,
        })
    return rows


def parse_notice(text: str) -> dict:
    body = re.sub(r"\s+", " ", text).strip()
    index_matches = {f"{int(a)}/{b}" for a, b in INDEX.findall(re.search(r"Index Number\s+([\d/]+)", body, re.I).group(1))} if re.search(r"Index Number\s+([\d/]+)", body, re.I) else set()
    address = re.search(r"Said premises known as\s+(.+?),\s*([A-Za-z ]+),\s*NY\s+(\d{5})", body, re.I)
    bbl = re.search(r"Block\s+(\d+)\s+Lot\s+(\d+)", body, re.I)
    lien = re.search(r"Approximate amount of lien\s*\$\s*([\d,]+(?:\.\d{2})?)", body, re.I)
    sale = re.search(r"on\s+(October\s+\d{1,2},\s*20\d{2})\s+at\s+(\d{1,2}:\d{2}\s*[ap]\.m\.)", body, re.I)
    sale_place = re.search(r"sell\s+at\s+public\s+auction\s+at\s+(.+?)\s+on\s+October\s+\d{1,2},\s*20\d{2}", body, re.I)
    judgment_date = re.search(r"Judgment of Foreclosure and Sale dated\s+([A-Za-z]+\s+\d{1,2},\s*20\d{2})", body, re.I)
    referee = re.search(r"([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){1,3}),\s*ESQ\.,\s*Referee", body, re.I)
    plaintiff = re.search(r"NOTICE OF SALE\s+SUPREME COURT\s*-\s*COUNTY OF QUEENS\.?\s*(.+?),\s*Plaintiff\s+-against-", body, re.I)
    attorney = re.search(r"\n?([A-Z][A-Z &.,'-]{4,}?)\s+Attorney\(s\) for Plaintiff", text, re.I)
    filed = re.search(r"FILED:\s*QUEENS COUNTY CLERK\s+(\d{2}/\d{2}/\d{4})\s+(\d{1,2}:\d{2}\s*[AP]M).*?NYSCEF DOC\. NO\.\s*(\d+)", body, re.I)
    return {
        "index_number": next(iter(index_matches)) if len(index_matches) == 1 else None,
        "sale_date": datetime.strptime(sale.group(1), "%B %d, %Y").date().isoformat() if sale else None,
        "sale_time": sale.group(2) if sale else None,
        "sale_place": sale_place.group(1).strip(" ,") if sale_place else None,
        "judgment_date": datetime.strptime(judgment_date.group(1), "%B %d, %Y").date().isoformat() if judgment_date else None,
        "street": address.group(1).strip() if address else None,
        "city": address.group(2).strip() if address else None,
        "state": "NY" if address else None,
        "zip": address.group(3) if address else None,
        "block": bbl.group(1) if bbl else None,
        "lot": bbl.group(2) if bbl else None,
        "approximate_lien_amount": float(lien.group(1).replace(",", "")) if lien else None,
        "referee": referee.group(1) if referee else None,
        "notice_plaintiff": plaintiff.group(1).strip() if plaintiff else None,
        "notice_plaintiff_attorney": attorney.group(1).strip() if attorney else None,
        "notice_filing_date": datetime.strptime(filed.group(1), "%m/%d/%Y").date().isoformat() if filed else None,
        "notice_document_number": int(filed.group(3)) if filed else None,
        "raw_financial_phrase": re.search(r"Approximate amount of lien\s*\$\s*[\d,]+(?:\.\d{2})?", body, re.I).group(0) if lien else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("data/ny_foreclosures/queens_case_bundle.json"))
    args = parser.parse_args()
    docs = {}
    for path in sorted(args.folder.glob("*.pdf")):
        text, digest = read_pdf(path)
        docs[path.name] = {"text": text, "sha256": digest}
    notice_file = next((name for name in docs if "NOTICE_OF_SALE" in name.upper()), None)
    case_file = next((name for name in docs if "CASE DETAIL" in name.upper()), None)
    appearances_file = next((name for name in docs if "APPEARANCE DETAIL" in name.upper()), None)
    if not notice_file or not case_file or not appearances_file:
        raise SystemExit("Expected one Notice of Sale, one WebCivil Case Detail, and one Appearance Detail PDF")
    notice = parse_notice(docs[notice_file]["text"])
    case = parse_case_detail(docs[case_file]["text"])
    history = parse_appearances(docs[appearances_file]["text"])
    indexes = {notice.get("index_number"), case.get("index_number")}
    appearance_text = docs[appearances_file]["text"]
    appearance_index = re.search(r"Index Number:\s*([\d/]+)", appearance_text, re.I)
    if appearance_index:
        indexes.add(next(iter({f"{int(a)}/{b}" for a, b in INDEX.findall(appearance_index.group(1))}), None))
    if len(indexes) != 1 or None in indexes:
        raise SystemExit(f"Source PDFs do not agree on one index number: {sorted(str(x) for x in indexes)}")
    block, lot = notice.get("block"), notice.get("lot")
    street = notice.get("street")
    if street:
        street = street.title()
        street = re.sub(r"(\d+)(St|Nd|Rd|Th)\b", lambda m: m.group(1) + m.group(2).lower(), street)
    record = {
        "county": "Queens",
        "index_number": notice["index_number"],
        "court": case.get("court"),
        "court_part": "FORECLOSURE AUCTION PART",
        "sale_type": "Court foreclosure auction",
        "source_system": "ny_court_foreclosure_auction",
        "case_caption": case.get("case_caption"),
        "case_type": case.get("case_type"),
        "track": case.get("track"),
        "case_status": None,
        "disposition_date": case.get("disposition_date"),
        "scheduled_auction_date": notice.get("sale_date"),
        "scheduled_auction_time": notice.get("sale_time"),
        "scheduled_auction_place": notice.get("sale_place"),
        "status": "Scheduled" if notice.get("sale_date") and notice["sale_date"] >= date.today().isoformat() else "Unknown",
        "raw_status": None,
        "plaintiff": notice.get("notice_plaintiff") or case.get("plaintiff"),
        "defendant": case.get("defendant"),
        "property_details": {
            "address": street, "raw_address": notice.get("street"),
            "city": notice.get("city").title() if notice.get("city") else None, "state": notice.get("state"),
            "zip": notice.get("zip"), "borough_block_lot": f"4-{int(block):05d}-{int(lot):04d}" if block and lot else None,
            "tax_parcel_id": None, "block": block, "lot": lot, "section": None,
            "original_mortgage_amount": None, "unpaid_principal_balance": None,
            "amount_claimed_due": None, "judgment_amount": None,
            "approximate_lien_amount": notice.get("approximate_lien_amount"),
            "amount_source_text": notice.get("raw_financial_phrase"),
        },
        "referee_name": notice.get("referee"),
        "plaintiff_attorney": notice.get("notice_plaintiff_attorney"),
        "defendant_attorney": case.get("defendant_attorney"),
        "assigned_justice": case.get("assigned_justice"),
        "case_metadata": {**{key: case.get(key) for key in ("cms_index_number", "rji_filed", "disposition_date")},
                           "judgment_date": notice.get("judgment_date"),
                           "court_listed_plaintiff": case.get("plaintiff")},
        "appearance_history": history,
        "efiled_documents_summary": {
            "nyscef_accessible": True,
            "docket_url": None,
            "initiating_doc": None,
            "documents": [{
                "document_number": notice.get("notice_document_number"),
                "document_type": "NOTICE OF SALE",
                "filing_date": notice.get("notice_filing_date"),
                "title": notice_file,
                "pdf_accessible": True,
                "extraction_priority": "sale_notice",
            }],
            "note": "The supplied Notice of Sale bears a NYSCEF filing stamp. The docket and initiating complaint were not included in this PDF bundle.",
        },
        "source_metadata": {
            "calendar_url": "https://iapps.courts.state.ny.us/webcivil/FCASCalendarSearch",
            "case_detail_url": None,
            "appearance_detail_url": None,
            "nyscef_url": None,
            "source_files": [{"file": name, "sha256": info["sha256"]} for name, info in docs.items()],
            "extracted_at": datetime.now(timezone.utc).isoformat(),
        },
        "extraction_notes": [
            "The notice says approximate amount of lien; it is preserved separately and is not labeled a judgment or unpaid principal balance.",
            "Auction status is normalized as Scheduled from the future calendar event; no outcome is stated for that event.",
            "Original mortgage principal, unpaid balance, and judgment amount are absent from the supplied PDFs.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps([record], indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"output": str(args.output), "records": 1, "index_number": record["index_number"],
                      "appearance_rows": len(history), "source_pdfs": len(docs),
                      "approximate_lien_amount": notice.get("approximate_lien_amount"),
                      "judgment_amount": None}, indent=2))


if __name__ == "__main__":
    main()
