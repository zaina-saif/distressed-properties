from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass
class RawSheriffSale:
    county: str
    sheriff_number: str
    address: str
    sale_date: datetime | None
    status: str
    upset_price: Decimal | None
    source_url: str
    raw_payload: dict[str, Any]

    plaintiff: str | None = None
    defendant: str | None = None
    judgment_amount: Decimal | None = None
    plaintiff_attorney: str | None = None
    court_case_number: str | None = None
    block: str | None = None
    lot: str | None = None
    qualifier: str | None = None
    detail_fields: dict[str, Any] = field(default_factory=dict)
    state: str = "NJ"


class CivilViewAdapter(ABC):
    @abstractmethod
    async def fetch_sale_index(self) -> list[str]:
        """Return sheriff numbers available from the listing."""

    @abstractmethod
    async def fetch_sale(
        self,
        source_id: str,
    ) -> RawSheriffSale:
        """Return one parsed sheriff-sale record."""

    async def enrich_sale_detail(
        self,
        sale: RawSheriffSale,
    ) -> RawSheriffSale:
        """Optionally enrich a sale using its detail page."""

        return sale
