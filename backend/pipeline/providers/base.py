from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class ValuationResult:
    provider: str
    provider_property_id: str | None
    estimated_value: Decimal
    low_value: Decimal | None
    high_value: Decimal | None
    formatted_address: str
    address_line_1: str | None
    city: str | None
    state: str | None
    zip_code: str | None
    comparable_count: int
    raw_response: dict[str, Any]


class ValuationProvider(ABC):
    @abstractmethod
    async def get_valuation(self, address: str) -> ValuationResult:
        """Return a current value estimate for one normalized address."""
