import hashlib
import re
from datetime import datetime
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from pipeline.adapters.base import RawSheriffSale


class NYCountyPageAdapter:
    """Parse explicitly published sales from supported official NY county pages."""

    def __init__(self, county: str, source_url: str, timeout: int = 30):
        self.county = county
        self.source_url = source_url
        self.timeout = timeout

    async def fetch(self) -> list[RawSheriffSale]:
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            response = await client.get(self.source_url)
        response.raise_for_status()
        if self.county == "Erie":
            return self.parse_erie(response.text)
        if self.county == "Orange":
            return self.parse_orange(response.text)
        raise ValueError(f"Unsupported NY county page: {self.county}")

    def parse_erie(self, html: str) -> list[RawSheriffSale]:
        soup = BeautifulSoup(html, "html.parser")
        records = []
        pattern = re.compile(
            r"(?P<date>[A-Z][a-z]+\s+\d{1,2},\s+\d{4})\s*-\s*Sale of\s+"
            r"(?P<address>.+?\bNY\s+\d{5})(?:\s*-\s*(?P<status>Cancelled|Canceled))?$",
            re.I,
        )
        for link in soup.find_all("a", href=True):
            row_text = link.parent.get_text(" ", strip=True)
            match = pattern.search(row_text)
            if not match:
                continue
            detail_url = urljoin(self.source_url, link["href"])
            source_id = "ERIE-" + hashlib.sha256(detail_url.encode()).hexdigest()[:12].upper()
            records.append(RawSheriffSale(
                county="Erie",
                state="NY",
                sheriff_number=source_id,
                address=match.group("address"),
                sale_date=datetime.strptime(match.group("date"), "%B %d, %Y"),
                status="cancelled" if match.group("status") else "scheduled",
                upset_price=None,
                source_url=detail_url,
                raw_payload={
                    "listing_text": row_text,
                    "identifier_is_synthetic": True,
                    "official_listing_url": self.source_url,
                },
            ))
        return records

    def parse_orange(self, html: str) -> list[RawSheriffSale]:
        soup = BeautifulSoup(html, "html.parser")
        page_text = soup.get_text(" ", strip=True)
        docket = re.search(r"Civil Docket\s+([A-Za-z0-9-]+)", page_text, re.I)
        sale = re.search(r"Sale to take place\s+([A-Z][a-z]+\s+\d{1,2},\s+\d{4})", page_text, re.I)
        detail_link = next((link for link in soup.find_all("a", href=True)
                            if re.search(r"\bNY\s+\d{5}", link.get_text(" ", strip=True), re.I)), None)
        address = re.search(
            r"(.+?\bNY\s+\d{5})",
            detail_link.get_text(" ", strip=True) if detail_link else "",
            re.I,
        )
        parcel = re.search(r"Section\s+([^\s]+)\s+Block\s+([^\s]+)\s+Lot\s+([^\s]+)", page_text, re.I)
        if not (docket and sale and address):
            return []

        detail_url = urljoin(self.source_url, detail_link["href"]) if detail_link else self.source_url
        return [RawSheriffSale(
            county="Orange",
            state="NY",
            sheriff_number=docket.group(1),
            court_case_number=docket.group(1),
            address=address.group(1).strip(),
            sale_date=datetime.strptime(sale.group(1), "%B %d, %Y"),
            status="scheduled",
            upset_price=None,
            source_url=detail_url,
            block=parcel.group(2) if parcel else None,
            lot=parcel.group(3).rstrip(".,") if parcel else None,
            raw_payload={
                "listing_text": page_text,
                "section": parcel.group(1) if parcel else None,
                "block": parcel.group(2) if parcel else None,
                "lot": parcel.group(3).rstrip(".,") if parcel else None,
                "official_listing_url": self.source_url,
            },
        )]
