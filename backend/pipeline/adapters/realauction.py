"""RealAuction county auction sites: Ohio sheriff sales (*.sheriffsaleauction.ohio.gov),
Florida clerk foreclosure sales and Colorado Public Trustee sales (*.realforeclose.com).

Public pages only: the calendar lists sale days, and each day's auctions load
ten at a time from the site's own AJAX endpoint. Tax-deed days are skipped."""
import json
import re
import time
from datetime import date, datetime

import httpx

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"}
# The AJAX response abbreviates repeated markup with these tokens.
TOKENS = {"@A": '<div class="', "@B": "</div>", "@C": 'class="', "@D": "<tr><td", "@E": "AUCTION",
          "@F": "</td><td", "@G": "</td></tr>", "@H": '<span class="', "@I": "table", "@J": "</span>"}
DAY = re.compile(r"""dayid='(\d{2}/\d{2}/\d{4})'(.*?)(?=<div[^>]*class='CALBOX|\Z)""", re.S)
# Sites expand the tokens differently, so match rows by their label/data classes.
FIELD = re.compile(r'AD_LBL"[^>]*>(.*?)</t[dh]>\s*<td[^>]*AD_DTA[^>]*>(.*?)</td>', re.S)


def decode(html):
    for token, markup in TOKENS.items():
        html = html.replace(token, markup)
    return html


def text(value):
    return " ".join(re.sub(r"<[^>]+>", " ", value).replace("&nbsp;", " ").replace("&amp;", "&").split())


def calendar_days(html):
    """(date, auction kind, scheduled count) for each sale day on a calendar page."""
    days = []
    for day, body in DAY.findall(html):
        kind = text(body[body.find(">") + 1:].split("CALMSG")[0].rsplit("<", 1)[0]).lstrip("0123456789 ").strip()
        scheduled = re.search(r'CALSCH">\s*(\d+)', body)
        days.append((datetime.strptime(day, "%m/%d/%Y").date(), kind, int(scheduled.group(1)) if scheduled else 0))
    return days


def parse_items(html):
    """One dict per auction: its id, status panel text and labelled detail rows."""
    items = []
    for chunk in decode(html).split('id="AITEM_')[1:]:
        auction_id = chunk.split('"', 1)[0]
        fields, previous = {}, None
        for label, value in FIELD.findall(chunk):
            label, value = text(label).rstrip(":"), text(value)
            # The city/ZIP line of an address has an empty label.
            key = f"{previous} 2" if not label and previous else label
            fields[key] = value
            previous = label or previous
        stats = text(chunk[chunk.find(">") + 1:].split("AUCTION_DETAILS")[0].rsplit("<", 1)[0])
        items.append({"auction_id": auction_id, "status_text": stats, "fields": fields})
    return items


class RealAuctionAdapter:
    def __init__(self, base_url, months=3, timeout=30):
        self.base_url = base_url.rstrip("/") + "/index.cfm"
        self.months, self.timeout = months, timeout

    def _items(self, client, sale_day, area):
        """All auctions in one area of a sale day ("W" upcoming, "C" closed or cancelled)."""
        found, seen = [], set()
        for page in range(100):
            response = client.get(self.base_url, headers={"X-Requested-With": "XMLHttpRequest"}, params={
                "zaction": "AUCTION", "Zmethod": "UPDATE", "FNC": "LOAD", "AREA": area,
                "PageDir": "0" if page == 0 else "1", "doR": "1",
                "tx": str(int(time.time() * 1000)), "bypassPage": "0"})
            response.raise_for_status()
            body = response.text
            payload = json.loads(body[body.index("{"):]) if "{" in body else {}
            batch = [item for item in parse_items(payload.get("retHTML", "")) if item["auction_id"] not in seen]
            if not batch:
                break
            seen.update(item["auction_id"] for item in batch)
            found.extend(batch)
        return found

    def fetch(self, today=None):
        """Every foreclosure auction on a sale day from today through the next few months."""
        today = today or date.today()
        records = []
        with httpx.Client(headers=HEADERS, timeout=self.timeout, follow_redirects=True) as client:
            days = {}
            for offset in range(self.months):
                month = date(today.year + (today.month - 1 + offset) // 12, (today.month - 1 + offset) % 12 + 1, 1)
                page = client.get(self.base_url, params={
                    "zaction": "USER", "zmethod": "CALENDAR",
                    "selCalDate": "{ts '" + month.strftime("%Y-%m-%d") + " 00:00:00'}"})
                page.raise_for_status()
                if "CALBOX" not in page.text:
                    raise RuntimeError("RealAuction calendar not found")
                for day, kind, count in calendar_days(page.text):
                    # Most sites label sale days "Foreclosure"; some (Mesa, CO) use "FC".
                    if day >= today and count and ("foreclos" in kind.lower() or kind.strip().upper() == "FC"):
                        days[day] = kind
            for day in sorted(days):
                client.get(self.base_url, params={"zaction": "AUCTION", "Zmethod": "PREVIEW",
                                                  "AUCTIONDATE": day.strftime("%m/%d/%Y")}).raise_for_status()
                for area in ("W", "C"):
                    for item in self._items(client, day, area):
                        records.append({**item, "sale_date": day.isoformat(), "area": area, "auction_kind": days[day]})
        return records
