"""Configurable CivilView adapter for counties using the shared SalesWeb portal."""
import re
from pipeline.adapters.monmouth import MonmouthCivilViewAdapter

class CountyCivilViewAdapter(MonmouthCivilViewAdapter):
    def __init__(self,county_name: str,county_id: int,sheriff_pattern: str=r"\b[A-Z]{1,4}-\d+\b",timeout: float=30.0) -> None:
        self.COUNTY_NAME=county_name
        self.COUNTY_ID=county_id
        self.SEARCH_URL=f"https://salesweb.civilview.com/Sales/SalesSearch?countyId={county_id}"
        self.SHERIFF_NUMBER_PATTERN=re.compile(sheriff_pattern,re.IGNORECASE)
        super().__init__(timeout=timeout)
