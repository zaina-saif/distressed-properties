"""SRI Services (sriservices.com): sheriff foreclosure sales for most Indiana counties.

The public property search at https://sriservices.com/properties loads its data
from a JSON API. Requests send the same API key the public site sends from every
visitor's browser; no login is needed, and SRI's robots.txt allows crawling.

Two calls per county:
  POST /api/property/carddetail   every listing for a county and date range
  POST /api/property/detail       one listing's case: judgment, plaintiff,
                                  attorney, minimum bid and, after the sale, the price
"""
from __future__ import annotations

import time
from datetime import date

import httpx

API = "https://sriservicesusermgmtprod.azurewebsites.net/api"
# Sent by the public sriservices.com site with every anonymous request.
PUBLIC_SITE_KEY = "9f8fd9fe5160294175e1c737567030f495d838a7922a678bc06e0a093910"
SITE_URL = "https://sriservices.com/properties"
FORECLOSURE = "F"


class SriClient:
    def __init__(self, timeout: float = 60, pause: float = 0.2):
        self.pause = pause
        self.http = httpx.Client(base_url=API, timeout=timeout, headers={
            "x-api-key": PUBLIC_SITE_KEY, "Accept": "application/json", "Content-Type": "application/json",
            "Origin": "https://sriservices.com", "Referer": SITE_URL})

    def close(self) -> None:
        self.http.close()

    def _request(self, method: str, path: str, **kwargs):
        for attempt in range(4):
            try:
                response = self.http.request(method, path, **kwargs)
                response.raise_for_status()
                time.sleep(self.pause)
                return response.json()
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if attempt == 3 or (status is not None and status < 500 and status != 429):
                    raise
                time.sleep(5 * (attempt + 1))

    def counties(self, state: str) -> list[str]:
        """County names as the API expects them ("St Joseph", "LaPorte")."""
        return sorted(item["id"] for item in self._request("GET", "/property/counties") if item.get("joinId") == state)

    def listings(self, state: str, county: str, start: date, end: date | None = None) -> list[dict]:
        """Foreclosure listings with an auction date from `start` (through `end` when given)."""
        body = {
            "auctionDateRange": {"startDate": start.isoformat(), "endDate": end.isoformat() if end else "",
                                 "compareOperator": ">"},
            "auctionStyle": "", "county": county, "propertySaleType": FORECLOSURE, "recordCount": 50000,
            "saleStatus": "", "searchText": "", "startIndex": 0, "state": state,
        }
        properties = self._request("POST", "/property/carddetail", json=body).get("properties") or []
        # The site drops repeated id/saleId pairs the same way.
        seen, unique = set(), []
        for item in properties:
            key = (item.get("id"), item.get("saleId"))
            if key not in seen:
                seen.add(key)
                unique.append(item)
        return unique

    def detail(self, listing: dict) -> dict:
        body = {"id": listing["id"], "propertyId": listing["propertyId"],
                "saleId": int(listing.get("originalSaleId") or listing.get("saleId") or 0),
                "saleType": listing.get("saleType") or FORECLOSURE}
        return self._request("POST", "/property/detail", json=body) or {}
