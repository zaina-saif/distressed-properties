"""Live copy of a sale's CivilView detail page.

CivilView only serves a SaleDetails page inside a session opened from that
county's search page, and it regenerates PropertyIds, so stored detail links
go stale within a day. This endpoint looks the sale up fresh by sheriff
number (open listings first, then the sold/cancelled search) and returns the
page's fields as structured data rather than raw HTML.
"""
from __future__ import annotations

import re
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any

import httpx
from bs4 import BeautifulSoup
from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from app.database.session import engine
from pipeline.scrape_nj_civilview import CIVILVIEW_COUNTIES
from pipeline.scrape_nj_sold_cancelled import _form_data

router = APIRouter(prefix="/api/v1/sale-pages", tags=["sale-pages"])

BASE_URL = "https://salesweb.civilview.com"
CACHE_SECONDS = 30 * 60
_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _clean(value: str) -> str:
    return " ".join(value.split())


def _find_detail_link(soup: BeautifulSoup, sheriff_number: str) -> str | None:
    wanted = sheriff_number.strip().upper()
    for row in soup.find_all("tr"):
        cells = [_clean(cell.get_text(" ", strip=True)).upper() for cell in row.find_all("td")]
        if wanted in cells:
            link = row.find("a", href=lambda href: href and "SaleDetails" in href)
            if link:
                return BASE_URL + link["href"] if link["href"].startswith("/") else link["href"]
    return None


def parse_detail_page(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.find("h1")
    fields = []
    for item in soup.select(".sale-detail-item"):
        label = item.select_one(".sale-detail-label")
        value = item.select_one(".sale-detail-value")
        if not label or not value:
            continue
        lines = [_clean(line) for line in value.get_text("\n").split("\n")]
        fields.append({"label": _clean(label.get_text(" ")).rstrip(":"), "value": "\n".join(line for line in lines if line)})
    history = []
    table = soup.find("table", id="longTable")
    for row in table.find_all("tr") if table else []:
        cells = [_clean(cell.get_text(" ", strip=True)) for cell in row.find_all("td")]
        if len(cells) >= 2 and cells[0]:
            history.append({"status": cells[0], "date": cells[1]})
    notes = [_clean(note.get_text(" ")) for note in soup.find_all(string=lambda s: s and s.strip().startswith("*"))]
    return {
        "title": _clean(heading.get_text(" ")) if heading else None,
        "fields": fields,
        "status_history": history,
        "notes": [note for note in notes if note],
    }


_TIME_RE = re.compile(
    r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(?:o['’]?\s?clock)?[,\s]*"
    r"(?:([ap])\.?\s?m\b\.?|in\s+the\s+(afternoon|morning))",
    re.IGNORECASE,
)
_LOCATION_RE = re.compile(
    r"(?:prevailing\s+time,?|in\s+the\s+afternoon|public\s+(?:vendue|venue|auction)(?:\s+to\s+be\s+held)?,?)"
    r"\s+at\s+(.{5,220}?(?:New\s+Jersey|\bN\.?J\b\.?)(?:\s+\d{5})?)",
    re.IGNORECASE,
)


def parse_sale_logistics(notice: str | None) -> dict[str, str | None]:
    """Sale time and place from a NJ sheriff's sale notice, e.g. "...at 2:00
    P.M. prevailing time at Commissioner's Meeting Room, ..., Paterson, New
    Jersey to wit". Returns None for anything the notice does not state."""
    text_ = " ".join((notice or "").split())
    time_text = location = None
    match = _TIME_RE.search(text_)
    if match:
        hour, minute, meridiem, part_of_day = match.groups()
        meridiem = (meridiem or ("p" if (part_of_day or "").lower() == "afternoon" else "a")).upper()
        time_text = f"{int(hour)}:{minute or '00'} {meridiem}M"
    match = _LOCATION_RE.search(text_)
    if match:
        location = re.sub(r"^the\s+", "", match.group(1).strip(" ,"), flags=re.IGNORECASE)
    return {"time": time_text, "location": location}


_county_typical: dict[str, tuple[float, dict[str, str | None]]] = {}


def county_typical_logistics(county: str) -> dict[str, str | None]:
    """Most common time and place across the county's current sale notices."""
    cached = _county_typical.get(county)
    if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1]
    with engine.connect() as connection:
        notices = connection.execute(text("""
            SELECT description_text FROM sheriff_sales
            WHERE state='NJ' AND county=:county AND description_text IS NOT NULL
              AND strpos(lower(current_status),'scheduled')>0
        """), {"county": county}).scalars().all()
    parsed = [parse_sale_logistics(notice) for notice in notices]
    result: dict[str, str | None] = {}
    for key in ("time", "location"):
        values = Counter(item[key] for item in parsed if item[key])
        result[key] = values.most_common(1)[0][0] if values else None
    _county_typical[county] = (time.monotonic(), result)
    return result


def _fetch(county_id: int, sheriff_number: str) -> dict[str, Any] | None:
    search_url = f"{BASE_URL}/Sales/SalesSearch?countyId={county_id}"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; NJSheriffSalePro/1.0)"}
    with httpx.Client(headers=headers, timeout=20, follow_redirects=True) as client:
        search = client.get(search_url)
        search.raise_for_status()
        soup = BeautifulSoup(search.text, "html.parser")
        link = _find_detail_link(soup, sheriff_number)
        listing = "open"
        if link is None:
            history = client.post(search_url, data=_form_data(soup, "0"), headers={"Referer": search_url})
            history.raise_for_status()
            link = _find_detail_link(BeautifulSoup(history.text, "html.parser"), sheriff_number)
            listing = "sold_or_cancelled"
        if link is None:
            return None
        detail = client.get(link)
        detail.raise_for_status()
        if detail.url.path.rstrip("/").lower() != "/sales/saledetails":
            return None
    page = parse_detail_page(detail.text)
    page.update({"listing": listing, "county_search_url": search_url})
    return page


@router.get("/{sheriff_sale_id}")
def get_sale_page(sheriff_sale_id: str) -> dict[str, Any]:
    cached = _cache.get(sheriff_sale_id)
    if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1]
    with engine.connect() as connection:
        sale = connection.execute(text("""
            SELECT state, county, sheriff_number, description_text FROM sheriff_sales WHERE id::text = :id
        """), {"id": sheriff_sale_id}).mappings().first()
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")
    county_id = CIVILVIEW_COUNTIES.get(sale["county"]) if sale["state"] == "NJ" else None
    if county_id is None:
        raise HTTPException(status_code=404, detail=f"{sale['county']} County does not publish sale pages on CivilView")
    try:
        page = _fetch(county_id, sale["sheriff_number"])
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="CivilView could not be reached") from exc
    if page is None:
        raise HTTPException(
            status_code=404,
            detail=f"Sheriff # {sale['sheriff_number']} is no longer listed on the {sale['county']} County CivilView portal",
        )
    live_notice = next((f["value"] for f in page["fields"] if f["label"].lower() == "description"), None)
    logistics = parse_sale_logistics(live_notice or sale["description_text"])
    typical = county_typical_logistics(sale["county"])
    sale_date = next((f["value"] for f in page["fields"] if f["label"].lower() in {"sales date", "sale date"}), None)
    page["sale_logistics"] = {
        "date": sale_date,
        **{key: logistics[key] or typical[key] for key in ("time", "location")},
        "basis": {key: "notice" if logistics[key] else "county_typical" if typical[key] else None
                  for key in ("time", "location")},
    }
    page.update({
        "county": sale["county"],
        "sheriff_number": sale["sheriff_number"],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "CivilView SalesWeb (live)",
    })
    _cache[sheriff_sale_id] = (time.monotonic(), page)
    return page
