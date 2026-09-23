"""Collect public Florida real-estate sale and disposition listings."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

FDOT_URL = "https://rowsurplus.fdot.gov/"
FDOT_API = "https://rowsurplus.fdot.gov/api/SurplusProperty/Search/1/500/default/false"
SWFWMD_URL = "https://www.swfwmd.state.fl.us/business/land-for-sale-listing"
TREASURY_URL = "https://www.treasury.gov/auctions/treasury/rp/realprop.shtml"
TREASURY_DETAIL_BASE = "https://www.treasury.gov/auctions/treasury/rp/"
OUTPUT = Path("data/sheriff_sales/florida_public_real_estate_listings.json")
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"


def _get_public_text(url: str, client: httpx.Client) -> str:
    response = client.get(url)
    if response.status_code != 403:
        response.raise_for_status()
        return response.text
    # SWFWMD intermittently returns 403 for Python HTTP clients while allowing
    # the same public page through curl. Retry with the system's ordinary HTTP
    # client; this does not handle or bypass a challenge page.
    result = subprocess.run(
        ["curl", "-sS", "-L", "--max-time", "45", "-A", USER_AGENT, url],
        check=True, capture_output=True, text=True, timeout=50,
    )
    if "<html" not in result.stdout.lower() and "<!doctype" not in result.stdout.lower():
        raise ValueError(f"Expected public HTML from {url}")
    return result.stdout


def _clean(value: str) -> str:
    return " ".join(value.split()).strip()


def _money(text: str | None) -> str | None:
    if not text:
        return None
    match = re.search(r"\$\s*([\d,]+(?:\.\d{1,2})?)", text)
    return str(Decimal(match.group(1).replace(",", "")).quantize(Decimal("0.01"))) if match else None


def parse_fdot(payload: list[dict]) -> list[dict]:
    records = []
    for item in payload:
        p = item.get("Properties") or {}
        county = (p.get("County") or {}).get("Description")
        property_number = _clean(str(p.get("PropertyNumber") or ""))
        if not county or not property_number:
            continue
        records.append({
            "source_system": "fl_fdot_surplus_property",
            "source_url": FDOT_URL,
            "state": "FL",
            "county": county.title(),
            "record_id": f"fdot-object:{item.get('ObjectId') or property_number}",
            "property_number": property_number,
            "street_address": f"FDOT property {property_number}",
            "normalized_address": f"FDOT property {property_number} — {_clean(p.get('Description') or '')}, {county.title()} County, FL",
            "city": _clean(p.get("City") or f"{county.title()} County"),
            "zip_code": _clean(str(p.get("ZipCode") or "")) or None,
            "property_type": "FDOT surplus right-of-way property",
            "acreage": float(p.get("SizeInAcres") or 0) or None,
            "square_feet": int(round(float(p.get("SizeInSquareFeet") or 0))) or None,
            "latitude": p.get("Latitude"),
            "longitude": p.get("Longitude"),
            "listing_description": _clean(p.get("Description") or ""),
            "current_status": "listed",
            "sale_date": None,
            "starting_bid": None,
            "judgment_amount": None,
        })
    return records


def parse_swfwmd(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    records = []
    county = None
    for node in soup.select("h2, table"):
        if node.name == "h2":
            county_match = re.search(r"(.+?)\s+County", node.get_text(" ", strip=True), re.I)
            county = county_match.group(1).title() if county_match else None
            continue
        if not county:
            continue
        for row in node.select("tr")[1:]:
            cells = row.find_all(["th", "td"])
            if len(cells) < 4:
                continue
            anchor = cells[0].select_one("a")
            property_id = re.sub(r"\s*\(map\).*", "", cells[0].get_text(" ", strip=True), flags=re.I).strip(" »")
            property_id = _clean(property_id)
            if not property_id or "for sale" not in cells[3].get_text(" ", strip=True).lower():
                continue
            property_name = _clean(node.caption.get_text(" ", strip=True)) if node.caption else None
            acreage_text = cells[1].get_text(" ", strip=True).replace(",", "")
            acreage = float(acreage_text) if re.fullmatch(r"\d+(?:\.\d+)?", acreage_text) else None
            map_url = urljoin(SWFWMD_URL, anchor.get("href")) if anchor else SWFWMD_URL
            label = f"{property_id} — {property_name}" if property_name else property_id
            terms = _clean(cells[2].get_text(" ", strip=True))
            sale_note = _clean(cells[3].get_text(" ", strip=True))
            records.append({
                "source_system": "fl_swfwmd_land_for_sale",
                "source_url": SWFWMD_URL,
                "state": "FL",
                "county": county,
                "record_id": f"swfwmd:{property_id}",
                "property_number": property_id,
                "street_address": f"SWFWMD property {label}",
                "normalized_address": f"SWFWMD property {label}, {county} County, FL",
                "city": f"{county} County",
                "zip_code": None,
                "property_type": "Government land for sale",
                "acreage": acreage,
                "square_feet": None,
                "latitude": None,
                "longitude": None,
                "listing_description": f"{sale_note}. Approx. {acreage:g} acres. Terms: {terms}. Map: {map_url}",
                "current_status": "listed",
                "sale_date": None,
                "starting_bid": None,
                "judgment_amount": None,
            })
    return records


def _field_value(soup: BeautifulSoup, label: str) -> str | None:
    for bold in soup.find_all(["b", "strong"]):
        if _clean(bold.get_text(" ", strip=True)).rstrip(":").lower() == label.lower():
            parent = bold.parent
            while parent and parent.name not in ("tr", "td"):
                combined = _clean(parent.get_text(" ", strip=True))
                if combined.lower().startswith(label.lower()):
                    remainder = combined[len(bold.get_text(" ", strip=True)):].strip(" :")
                    if remainder:
                        return remainder
                parent = parent.parent
    return None


def parse_treasury_index(html: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for row in soup.select("tr"):
        text = _clean(row.get_text(" ", strip=True))
        if "Florida" not in text or "ONLINE AUCTION" not in text.upper():
            continue
        detail = next((a.get("href") for a in row.select("a[href]") if re.search(r"\.shtml$", a.get("href", ""), re.I) and "112bruni" not in a.get("href", "")), None)
        if detail:
            items.append((urljoin(TREASURY_DETAIL_BASE, detail), text))
    unique = {url: text for url, text in items}
    return list(unique.items())


def parse_treasury_detail(html: str, url: str, index_text: str) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    text = _clean(soup.get_text(" ", strip=True))
    sale_number = re.search(r"Sale\s+(?:Number|#):?\s*([0-9]{2}-[0-9]{2}-[0-9]{3})", text, re.I)
    address = re.search(r"(\d+\s+[^,]+,\s*[^,]+,\s*Florida\s+\d{5})", title or index_text, re.I)
    sale_date = re.search(r"(?:Auction Date and Time:|ONLINE AUCTION DAT\s*E:)\s*([A-Za-z]+,?\s+[A-Za-z]+\s+\d{1,2},\s+20\d{2})", text, re.I)
    record_id = sale_number.group(1) if sale_number else None
    if not address or not record_id:
        return None
    addr = _clean(address.group(1))
    address_parts = re.match(r"(.+?),\s*(.+?),\s*Florida\s+(\d{5})", addr, re.I)
    if not address_parts:
        return None
    details = text
    living = re.search(r"Living Space:\s*([\d,]+)\s*(?:±\s*)?sq\.\s*ft", details, re.I)
    lot_sf = re.search(r"Site Area:\s*([\d,]+)\s*(?:±\s*)?sq\.\s*ft", details, re.I)
    year_built = re.search(r"Year Built:\s*(\d{4})", details, re.I)
    parcel = re.search(r"Parcel\s+No:\s*([0-9-]+)", details, re.I)
    bedrooms = re.search(r"(\d+)\s+bedrooms", details, re.I)
    bathrooms = re.search(r"(\d+(?:\.\d+)?)\s+baths?", details, re.I)
    sale = None
    if sale_date:
        try:
            sale = datetime.strptime(sale_date.group(1).replace(",", ""), "%A %B %d %Y").date().isoformat()
        except ValueError:
            try:
                sale = datetime.strptime(sale_date.group(1), "%A, %B %d, %Y").date().isoformat()
            except ValueError:
                pass
    return {
        "source_system": "fl_us_treasury_real_property",
        "source_url": url,
        "state": "FL",
        "county": "Palm Beach",
        "record_id": f"treasury:{record_id}",
        "property_number": parcel.group(1) if parcel else None,
        "street_address": address_parts.group(1),
        "normalized_address": f"{address_parts.group(1)}, {address_parts.group(2)}, FL {address_parts.group(3)}",
        "city": address_parts.group(2),
        "zip_code": address_parts.group(3),
        "property_type": "Residential duplex",
        "acreage": (float(lot_sf.group(1).replace(",", "")) / 43560) if lot_sf else None,
        "square_feet": int(living.group(1).replace(",", "")) if living else None,
        "bedrooms": float(bedrooms.group(1)) if bedrooms else None,
        "bathrooms": float(bathrooms.group(1)) if bathrooms else None,
        "year_built": int(year_built.group(1)) if year_built else None,
        "listing_description": details,
        "current_status": "scheduled",
        "sale_date": sale,
        "starting_bid": _money(_field_value(soup, "Starting Bid")),
        "judgment_amount": None,
    }


def collect() -> dict:
    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(timeout=45, follow_redirects=True, headers=headers) as client:
        fdot = client.get(FDOT_API)
        fdot.raise_for_status()
        treasury = client.get(TREASURY_URL)
        treasury.raise_for_status()
        swfwmd_html = _get_public_text(SWFWMD_URL, client)
        records = parse_fdot(fdot.json()) + parse_swfwmd(swfwmd_html)
        for url, index_text in parse_treasury_index(treasury.text):
            detail = client.get(url)
            detail.raise_for_status()
            record = parse_treasury_detail(detail.text, url, index_text)
            if record:
                records.append(record)
    records.sort(key=lambda r: (r["county"], r["source_system"], r["record_id"]))
    return {
        "source_checked_date": date.today().isoformat(),
        "coverage_note": "Active Florida real-estate offers collected from FDOT right-of-way surplus, SWFWMD land-for-sale, and current U.S. Treasury Florida property auctions. FDOT listings may be available for purchase or lease; county foreclosure and sheriff feeds are maintained separately.",
        "records": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    snapshot = collect()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, indent=2) + "\n")
    from collections import Counter
    print(json.dumps({"records": len(snapshot["records"]), "by_source": Counter(r["source_system"] for r in snapshot["records"]), "output": str(args.output)}))


if __name__ == "__main__":
    main()
