"""NJ public-record source registry and capability matrix.

The registry is deliberately descriptive: it routes properties to sources and
records whether a source can be automated. It does not make a county-wide
claim that a missing result means clear title.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceCapability:
    jurisdiction: str
    source_name: str
    source_type: str
    url: str
    search_method: str
    document_types: tuple[str, ...]
    access_status: str
    automation_note: str
    freshness_behavior: str = "UNKNOWN"


NJ_COUNTY_CLERK_URLS = {
    "Atlantic": "https://www.atlantic-county.org/countyclerk/",
    "Bergen": "https://www.bergencountyclerk.gov/",
    "Burlington": "https://www.co.burlington.nj.us/192/County-Clerk",
    "Camden": "https://www.camdencounty.com/service/county-clerk/",
    "Cape May": "https://capemaycountynj.gov/242/County-Clerk",
    "Cumberland": "https://www.cumberlandcountynj.gov/CountyClerk",
    "Essex": "https://www.essexclerk.com/",
    "Gloucester": "https://www.gloucestercountynj.gov/CountyClerk",
    "Hudson": "https://www.hudsoncountyclerk.org/",
    "Hunterdon": "https://www.co.hunterdon.nj.us/countyclerk/",
    "Mercer": "https://www.mercercounty.org/government/county-clerk",
    "Middlesex": "https://www.middlesexcountynj.gov/government/departments/county-clerk",
    "Monmouth": "https://oprs.co.monmouth.nj.us/Oprs/clerk/ClerkHome.aspx?op=basic",
    "Morris": "https://www.morriscountyclerk.org/",
    "Ocean": "https://www.co.ocean.nj.us/OC/CountyClerk/",
    "Passaic": "https://www.passaiccountynj.org/government/county-clerk",
    "Salem": "https://www.salemcountynj.gov/departments/county-clerk/",
    "Somerset": "https://www.somersetcountynj.gov/government/elected-officials/county-clerk",
    "Sussex": "https://sussexcountyclerk.com/",
    "Union": "https://ucnj.org/county-clerk/",
    "Warren": "https://www.warrencountynj.org/departments/county-clerk/",
}

_DOCUMENTS = (
    "DEED", "MORTGAGE", "ASSIGNMENT_OF_MORTGAGE", "MORTGAGE_MODIFICATION",
    "DISCHARGE_OF_MORTGAGE", "LIS_PENDENS", "TAX_SALE_CERTIFICATE",
    "FEDERAL_TAX_LIEN", "CONSTRUCTION_LIEN", "CONDOMINIUM_LIEN",
    "MUNICIPAL_LIEN", "JUDGMENT", "OTHER_LIEN",
)


def county_capabilities(county: str | None) -> list[SourceCapability]:
    """Return the applicable county source plus explicit municipal gaps."""
    name = next((key for key in NJ_COUNTY_CLERK_URLS if key.lower() == (county or "").strip().lower()), county or "Unknown")
    if name == "Monmouth":
        return [SourceCapability(
            jurisdiction="Monmouth County",
            source_name="Monmouth County OPRS",
            source_type="COUNTY_LAND_RECORDS",
            url=NJ_COUNTY_CLERK_URLS[name],
            search_method="block/lot + municipality; owner fallback",
            document_types=_DOCUMENTS,
            access_status="SUPPORTED",
            automation_note="Public ASP.NET index is searchable without authentication; images and blocked workflows remain manual.",
            freshness_behavior="Retrieved timestamp is stored; the index does not expose a reliable source-updated timestamp.",
        )]
    return [SourceCapability(
        jurisdiction=f"{name} County",
        source_name=f"{name} County Clerk land records",
        source_type="COUNTY_LAND_RECORDS",
        url=NJ_COUNTY_CLERK_URLS.get(name, ""),
        search_method="parcel/block/lot, address, or owner where the county portal supports it",
        document_types=_DOCUMENTS,
        access_status="POSSIBLE" if name in {"Bergen", "Middlesex", "Essex", "Ocean", "Camden"} else "MANUAL_ONLY",
        automation_note="Portal-specific review is required; no automation is attempted until normal public access and terms are verified.",
        freshness_behavior="Unknown until the county portal exposes a source date or record history.",
    )]


def municipal_capabilities(municipality: str | None, county: str | None) -> list[SourceCapability]:
    """Return honest municipality-level capability placeholders.

    NJ tax, water, sewer, and stormwater systems are municipality/authority
    specific. A missing URL is represented as manual review, never as zero.
    """
    label = municipality or "the municipality"
    return [SourceCapability(
        jurisdiction=f"{label}, {county or 'NJ'}",
        source_name="Municipal tax / utility authorities",
        source_type="MUNICIPAL",
        url="",
        search_method="address + block/lot + PAMS PIN",
        document_types=("PROPERTY_TAX", "TAX_SALE_CERTIFICATE", "MUNICIPAL_LIEN", "WATER_SEWER", "STORMWATER"),
        access_status="MANUAL_ONLY",
        automation_note="Authority-specific portal or collector confirmation is required; no universal NJ endpoint exists.",
        freshness_behavior="Collector/authority confirmation date must be recorded manually.",
    )]
