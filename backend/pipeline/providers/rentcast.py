import os
from decimal import Decimal
from typing import Any

import httpx
from dotenv import load_dotenv

from pipeline.providers.base import ValuationProvider, ValuationResult


class RentCastValuationProvider(ValuationProvider):
    BASE_URL = "https://api.rentcast.io/v1/avm/value"

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        load_dotenv()
        self.api_key = api_key or os.getenv("RENTCAST_API_KEY")
        self.timeout = timeout

        if not self.api_key:
            raise RuntimeError("RENTCAST_API_KEY is not configured.")

    async def get_valuation(self, address: str) -> ValuationResult:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                self.BASE_URL,
                params={
                    "address": address,
                    "lookupSubjectAttributes": "true",
                    "compCount": 15,
                },
                headers={
                    "Accept": "application/json",
                    "X-Api-Key": self.api_key,
                },
            )

        if response.status_code == 401:
            raise RuntimeError(
                "RentCast rejected RENTCAST_API_KEY. Confirm the API key "
                "is copied from an active API plan in the RentCast dashboard."
            )

        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        subject = payload.get("subjectProperty") or {}

        if payload.get("price") is None:
            raise RuntimeError("RentCast returned no value estimate.")

        return ValuationResult(
            provider="rentcast",
            provider_property_id=subject.get("id"),
            estimated_value=Decimal(str(payload["price"])),
            low_value=(
                Decimal(str(payload["priceRangeLow"]))
                if payload.get("priceRangeLow") is not None
                else None
            ),
            high_value=(
                Decimal(str(payload["priceRangeHigh"]))
                if payload.get("priceRangeHigh") is not None
                else None
            ),
            formatted_address=subject.get("formattedAddress", ""),
            address_line_1=subject.get("addressLine1"),
            city=subject.get("city"),
            state=subject.get("state"),
            zip_code=subject.get("zipCode"),
            comparable_count=len(payload.get("comparables") or []),
            raw_response=payload,
        )
