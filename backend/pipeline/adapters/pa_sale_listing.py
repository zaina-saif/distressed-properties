import re
from datetime import datetime
from decimal import Decimal
from urllib.parse import urljoin
import httpx
from bs4 import BeautifulSoup
from pipeline.adapters.base import RawSheriffSale

class PASaleListingAdapter:
    def __init__(self,county,base_url,timeout=30): self.county,self.base_url,self.timeout=county,base_url,timeout
    async def fetch(self):
        async with httpx.AsyncClient(timeout=self.timeout,follow_redirects=True) as c: r=await c.get(self.base_url)
        r.raise_for_status(); soup=BeautifulSoup(r.text,"html.parser"); table=soup.find("table",class_="body-table")
        if table is None: raise RuntimeError("PA sale listing table not found")
        records=[]
        for row in table.find_all("tr")[1:]:
            cells=[c.get_text(" ",strip=True) for c in row.find_all("td")]
            if len(cells)<6 or not cells[0]: continue
            parties=re.split(r"\s+vs\.?\s+",cells[1],maxsplit=1,flags=re.I)
            status_text=cells[5]; date_match=re.search(r"(\d{1,2}/\d{1,2}/\d{4})",status_text)
            sale_date=datetime.strptime(date_match.group(1),"%m/%d/%Y") if date_match else None
            raw_status=status_text.split("(",1)[0].strip().lower()
            status={"active":"scheduled","active (p)":"scheduled","postponed":"adjourned",
                    "cancelled":"cancelled","stayed":"stayed"}.get(raw_status,raw_status or "unknown")
            amount=Decimal(re.sub(r"[^0-9.]","",cells[4]) or "0")
            link=row.find("a",href=True); source=urljoin(self.base_url,link["href"]) if link else self.base_url
            records.append(RawSheriffSale(county=self.county,state="PA",sheriff_number=cells[0],
              address=cells[3],sale_date=sale_date,status=status,upset_price=None,source_url=source,
              raw_payload={"case_participants":cells[1],"attorney":cells[2],"address":cells[3],
                "judgment":cells[4],"raw_status":cells[5]},plaintiff=parties[0] or None,
              defendant=parties[1] if len(parties)>1 else None,judgment_amount=amount,
              court_case_number=cells[0]))
        return records
