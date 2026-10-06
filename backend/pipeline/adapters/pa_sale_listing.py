"""PA county "Sheriff.SaleListing" portals (Butler, Centre, Cumberland, ...).

The portal page only holds the sale-date picker; listings load per sale from
PropertySales/SalesForCategory and PropertySales/SaleListingDetails."""
import re
from datetime import datetime, timedelta
from decimal import Decimal
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from pipeline.adapters.base import RawSheriffSale

STATUS = {"active": "scheduled", "active (p)": "scheduled", "postponed": "adjourned",
          "cancelled": "cancelled", "stayed": "stayed"}
# Some counties add the parcel as an address line: "UPI#: 110-86678-0-0000".
PARCEL_LINE = re.compile(r"\s*(?:UPI|Parcel|PIN|Map|Tax\s*(?:ID|Parcel))\b\s*(?:#|No\.?|Number)?\s*:?\s*", re.I)
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"}


def parse_listing(html, county, sale_date, base_url):
    """Rows of one sale's listing table."""
    table = BeautifulSoup(html, "html.parser").find("table")
    if table is None:
        raise RuntimeError("PA sale listing table not found")
    records = []
    for row in table.find_all("tr")[1:]:
        cells = row.find_all("td")
        if len(cells) < 6:
            continue
        text = [cell.get_text(" ", strip=True) for cell in cells]
        if not text[0]:
            continue
        parties = re.split(r"\s+vs\.?\s+", text[1], maxsplit=1, flags=re.I)
        status_match = re.match(r"\s*([^(]*?)\s*(?:\((\d{1,2}/\d{1,2}/\d{4})\))?\s*$", text[5])
        raw_status = status_match.group(1).lower() if status_match else text[5].lower()
        status_date = (datetime.strptime(status_match.group(2), "%m/%d/%Y")
                       if status_match and status_match.group(2) else None)
        status = STATUS.get(raw_status, raw_status or "unknown")
        # A postponement's date is the new sale date; other status dates
        # (cancelled, stayed) are when the status changed, not a sale date.
        effective_sale_date = status_date if status == "adjourned" and status_date else sale_date
        amount = re.sub(r"[^0-9.]", "", text[4])
        address_lines = list(cells[3].stripped_strings)
        parcel = next((PARCEL_LINE.sub("", line).strip() for line in address_lines if PARCEL_LINE.match(line)), None)
        link = row.find("a", href=True)
        records.append(RawSheriffSale(
            county=county, state="PA", sheriff_number=text[0], address=text[3],
            sale_date=effective_sale_date, status=status, upset_price=None,
            source_url=urljoin(base_url, link["href"]) if link else base_url,
            raw_payload={"case_participants": text[1], "attorney": text[2], "address": text[3],
                         "address_lines": address_lines, "parcel_number": parcel, "judgment": text[4],
                         "raw_status": text[5], "listed_sale_date": sale_date, "status_date": status_date},
            plaintiff=parties[0] or None, defendant=parties[1] if len(parties) > 1 else None,
            judgment_amount=Decimal(amount) if amount else None, court_case_number=text[0]))
    return records


class PASaleListingAdapter:
    def __init__(self, county, base_url, timeout=30):
        self.county, self.base_url, self.timeout = county, base_url, timeout

    async def fetch(self):
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, headers=HEADERS) as client:
            page = await client.get(self.base_url)
            page.raise_for_status()
            soup = BeautifulSoup(page.text, "html.parser")
            category = soup.find("select", id="SaleCategory")
            if category is None:
                raise RuntimeError("PA sale listing page has no sale category picker")
            root = re.search(r"const rootUrl\s*=\s*'([^']+)'", page.text)
            api = urljoin(str(page.url), (root.group(1) if root else "/Sheriff.SaleListing/") + "PropertySales/")
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            by_case = {}
            for option in category.find_all("option"):
                if "real estate" not in option.get_text().lower():
                    continue
                response = await client.post(api + "SalesForCategory", data={"id": option["value"]})
                response.raise_for_status()
                sales = sorted(
                    ((datetime(1970, 1, 1) + timedelta(milliseconds=int(re.search(r"-?\d+", sale["SaleDate"]).group())))
                     .replace(hour=0, minute=0), sale["SaleId"]) for sale in response.json())
                for sale_date, sale_id in sales:
                    if sale_date < today:
                        continue
                    listing = await client.get(api + "SaleListingDetails", params={
                        "activeOnly": "false", "crierSort": "true", "id": sale_id,
                        "searchAllSales": "false", "searchText": ""})
                    listing.raise_for_status()
                    for record in parse_listing(listing.text, self.county, sale_date, str(page.url)):
                        # A postponed case can appear under several sales; the
                        # latest listing reflects its current status.
                        by_case[record.sheriff_number] = record
            return list(by_case.values())
