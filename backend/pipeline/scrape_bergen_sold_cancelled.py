"""Scrape Bergen County CivilView's rolling sold/cancelled history."""
from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

from pipeline.adapters.civilview_county import CountyCivilViewAdapter
from pipeline.load_to_supabase import load_into_supabase
from pipeline.scrape_civilview import json_serializer


COUNTY_ID = 7
SEARCH_URL = f"https://salesweb.civilview.com/Sales/SalesSearch?countyId={COUNTY_ID}"


def _form_data(soup: BeautifulSoup, month: str) -> dict[str, str]:
    form = soup.find("form", id="search_form") or soup.find("form")
    if form is None:
        raise RuntimeError("CivilView search form was not found")
    data: dict[str, str] = {}
    for control in form.find_all(["input", "select"]):
        name = control.get("name")
        if not name:
            continue
        if control.name == "select":
            option = control.find("option", selected=True) or control.find("option")
            data[name] = str(option.get("value", "")) if option else ""
        elif control.get("type") in {"radio", "checkbox"} and not control.has_attr("checked"):
            continue
        else:
            data[name] = str(control.get("value", ""))
    data.update({"IsOpen": "false", "PropertyStatusDate": "", "MonthNumber": month})
    return data


def _classify(record: Any) -> Any:
    history = record.raw_payload.get("status_history", [])
    raw_values = [str(item.get("raw_status", "")).lower() for item in history]
    is_sold = any("purchas" in value or "sold" in value for value in raw_values)
    status = "sold" if is_sold else "cancelled"
    return replace(record, status=status, raw_payload={**record.raw_payload, "historical_search_status": status})


async def scrape(output: Path) -> Path:
    adapter = CountyCivilViewAdapter("Bergen", COUNTY_ID)
    records: dict[str, Any] = {}
    headers = adapter._browser_headers()
    async with httpx.AsyncClient(headers=headers, timeout=45, follow_redirects=True, cookies=adapter._cookies) as client:
        initial = await client.get(SEARCH_URL)
        initial.raise_for_status()
        adapter._cookies.update(initial.cookies)
        initial_soup = BeautifulSoup(initial.text, "html.parser")
        # MonthNumber=0 is the portal's unfiltered Sold/Cancelled search. It
        # returns the rolling historical window (currently the last 12 months)
        # and is broader than the future-month options shown in the form.
        months = ["0"]

        for month in months:
            response = await client.post(SEARCH_URL, data=_form_data(initial_soup, month), headers={"Referer": SEARCH_URL})
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            table = adapter._find_sales_table(soup)
            if table is None:
                raise RuntimeError(f"No Bergen results table for month {month}")
            header_map = adapter._get_header_map(table)
            rows = []
            for row in table.find_all("tr"):
                record = adapter._parse_row(row, header_map)
                if record is not None:
                    rows.append(record)
            print(f"Bergen rolling history: {len(rows)} sold/cancelled listings")

            for position, record in enumerate(rows, start=1):
                if record.sheriff_number in records:
                    continue
                try:
                    enriched = await adapter.enrich_record_from_detail_page(client, record)
                    enriched.raw_payload["historical_search_month"] = "rolling-last-12-months"
                    records[record.sheriff_number] = _classify(enriched)
                    print(f"  {position}/{len(rows)} {record.sheriff_number} -> {records[record.sheriff_number].status}")
                except Exception as exc:
                    record.raw_payload["detail_page_error"] = str(exc)
                    records[record.sheriff_number] = _classify(record)
                    print(f"  {position}/{len(rows)} {record.sheriff_number} -> detail error: {exc}")
                await asyncio.sleep(0.2)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps([asdict(record) for record in records.values()], indent=2, default=json_serializer) + "\n", encoding="utf-8")
    print(f"Saved {len(records)} unique Bergen sold/cancelled listings to {output}")
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("data/sheriff_sales/bergen_sold_cancelled.json"))
    parser.add_argument("--load", action="store_true", help="Load the scraped records into Supabase")
    args = parser.parse_args()
    path = asyncio.run(scrape(args.output))
    if args.load:
        load_into_supabase(path)


if __name__ == "__main__":
    main()
