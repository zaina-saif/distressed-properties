"""Configuration for the optional independent professional title-search link.

This module intentionally contains no provider API client.  The application
only exposes a configured outbound link for the user's own due-diligence step.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

from pydantic import BaseModel, Field


DEFAULT_PROVIDER_NAME = "ProTitleUSA"
DEFAULT_PROVIDER_URL = "https://www.protitleusa.com/"


class ProfessionalTitleSearch(BaseModel):
    provider_name: str = Field(min_length=1)
    provider_url: str
    relationship: str = "independent_third_party"


def _safe_provider_url(value: str | None) -> str:
    candidate = (value or DEFAULT_PROVIDER_URL).strip()
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return DEFAULT_PROVIDER_URL
    return candidate


def get_professional_title_search() -> ProfessionalTitleSearch:
    provider_name = (os.getenv("TITLE_SEARCH_PROVIDER_NAME") or "").strip() or DEFAULT_PROVIDER_NAME
    return ProfessionalTitleSearch(
        provider_name=provider_name,
        provider_url=_safe_provider_url(os.getenv("TITLE_SEARCH_PROVIDER_URL")),
    )
