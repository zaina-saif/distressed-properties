import asyncio
import json
from datetime import datetime
from decimal import Decimal

import httpx
from bs4 import BeautifulSoup

from pipeline.adapters.base import RawSheriffSale


class MonroeBid4AssetsAdapter:
    BASE_URL = "https://www.bid4assets.com/monroecountysheriffsales"
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/140.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    @staticmethod
    def _grid_rows(html: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        for script in soup.find_all("script"):
            content = script.string or script.get_text()
            marker = '"data":{"Data":'
            if "Auctions_grid" not in content or marker not in content:
                continue
            start = content.index(marker) + len('"data":')
            payload, _ = json.JSONDecoder().raw_decode(content[start:])
            return payload["Data"]
        raise RuntimeError("Bid4Assets Monroe auction grid data was not found")

    @staticmethod
    def _sale_dates(html: str) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        select = soup.find("select", id="SelectedSaleDateId")
        if select is None:
            return []
        today = datetime.now().date()
        return [
            value
            for option in select.find_all("option")
            if (value := str(option.get("value") or ""))
            and len(value) == 8
            and datetime.strptime(value, "%Y%m%d").date() >= today
        ]

    @staticmethod
    def _detail_address(html: str) -> str | None:
        soup = BeautifulSoup(html, "html.parser")
        specifics = soup.find("div", class_="item-specifics-table")
        if specifics is None:
            return None
        for row in specifics.find_all("tr"):
            cells = row.find_all(["th", "td"])
            if len(cells) >= 2 and cells[0].get_text(" ", strip=True).lower() == "address":
                return " ".join(cells[1].get_text(" ", strip=True).split())
        return None

    @staticmethod
    def _status(value: str) -> str:
        normalized = value.strip().lower()
        if normalized in {"preview", "active", "open"}:
            return "scheduled"
        if "postpon" in normalized:
            return "adjourned"
        if "stay" in normalized:
            return "stayed"
        if "cancel" in normalized or "withdraw" in normalized:
            return "cancelled"
        if "sold" in normalized or "closed" in normalized:
            return "sold"
        return normalized or "unknown"

    async def fetch(self) -> list[RawSheriffSale]:
        async with httpx.AsyncClient(
            headers=self.HEADERS,
            timeout=60,
            follow_redirects=True,
        ) as client:
            initial = await client.get(self.BASE_URL)
            initial.raise_for_status()
            dates = self._sale_dates(initial.text) or [datetime.now().strftime("%Y%m%d")]

            rows_by_id: dict[int, dict] = {}
            for sale_date in dates:
                response = await client.get(self.BASE_URL, params={"salesdate": sale_date})
                response.raise_for_status()
                for row in self._grid_rows(response.text):
                    rows_by_id[int(row["AuctionID"])] = row

            semaphore = asyncio.Semaphore(8)

            async def enrich(row: dict) -> tuple[dict, str | None]:
                async with semaphore:
                    response = await client.get(
                        f"https://www.bid4assets.com/auction/{row['AuctionID']}"
                    )
                    response.raise_for_status()
                    return row, self._detail_address(response.text)

            enriched = await asyncio.gather(*(enrich(row) for row in rows_by_id.values()))

        records: list[RawSheriffSale] = []
        for row, detail_address in enriched:
            auction_id = int(row["AuctionID"])
            sale_date = datetime.fromisoformat(row["SaleDate"])
            debt = row.get("DebtAmount")
            records.append(RawSheriffSale(
                county="Monroe",
                state="PA",
                sheriff_number=str(row.get("SheriffNumber") or row.get("CourtCase") or auction_id),
                address=detail_address or str(row.get("Address") or ""),
                sale_date=sale_date,
                status=self._status(str(row.get("AuctionStatusString") or "")),
                upset_price=None,
                source_url=f"https://www.bid4assets.com/auction/{auction_id}",
                raw_payload={
                    "auction_id": auction_id,
                    "parcel_number": row.get("Apn"),
                    "township": row.get("Township"),
                    "attorney": row.get("Attorney"),
                    "raw_status": row.get("AuctionStatusString"),
                    "minimum_bid": row.get("MinimumBid"),
                    "current_bid": row.get("CurrentBid"),
                    "current_bid_display": row.get("CurrentBidString"),
                },
                plaintiff=row.get("Plaintiff"),
                defendant=row.get("Defendant"),
                judgment_amount=Decimal(str(debt)) if debt is not None else None,
                court_case_number=row.get("CourtCase"),
            ))
        return records
