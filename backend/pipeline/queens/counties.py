"""New York Supreme Court counties the WebCivil/NYSCEF collector covers.

The collector began with Queens (hence the package name); every county uses the
same operator-assisted workflow. `webcivil` is the court's value in WebCivil's
court list (#cboCourt, captured 2026-10-11); `names` confirms that a calendar or
notice PDF belongs to the county.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class County:
    name: str  # as stored in properties.county and shown in NYSCEF ("<name> County Supreme Court")
    webcivil: str
    names: str  # regex that must appear in the county's calendars and notices

    @property
    def source(self) -> str:
        # Queens keeps the source its listings were first loaded under.
        return "nyc_queens_nyscef_foreclosure" if self.name == "Queens" else "ny_nyscef_foreclosure"

    @property
    def number_prefix(self) -> str:
        return self.name.upper().replace(" ", "-") + "-NYSCEF-"


COUNTIES = {county.name.lower(): county for county in [
    County("New York", "60", r"New\s+York\s+County|County\s+of\s+New\s+York|Manhattan"),
    County("Kings", "46", r"\bKings\b|Brooklyn"),
    County("Queens", "80", r"\bQueens\b"),
    County("Bronx", "124", r"\bBronx\b"),
    County("Richmond", "84", r"\bRichmond\b|Staten\s+Island"),
    County("Nassau", "58", r"\bNassau\b"),
    County("Suffolk", "102", r"\bSuffolk\b"),
    County("Westchester", "118", r"\bWestchester\b"),
    County("Orange", "70", r"\bOrange\b"),
    County("Onondaga", "66", r"\bOnondaga\b"),
    County("Erie", "28", r"\bErie\b"),
]}


def county(name: str) -> County:
    try:
        return COUNTIES[name.strip().lower()]
    except KeyError:
        raise ValueError(f"{name} is not a covered county; choose from {', '.join(c.name for c in COUNTIES.values())}") from None
