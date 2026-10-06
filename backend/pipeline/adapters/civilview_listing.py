"""CivilView SalesWeb listings for any county (salesweb.civilview.com).

The search page lists every current sale with a details link; column sets
differ by county, so only the link is taken from it. Each detail page holds
"Label:" / value lines and the status history. A detail page redirects home
unless the session has loaded that county's search page first."""
import re
import time
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

BASE = "https://salesweb.civilview.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"}
DATE = re.compile(r"\d{1,2}/\d{1,2}/\d{4}")


def search_url(county_id):
    return f"{BASE}/Sales/SalesSearch?countyId={county_id}"


def detail_links(html):
    return list(dict.fromkeys(re.findall(r"/Sales/SaleDetails\?PropertyId=\d+", html)))


def parse_detail(html):
    """Labelled fields (address lines kept separately) and the status history, newest first."""
    soup = BeautifulSoup(html, "html.parser")
    for element in soup(["script", "style", "nav", "header", "footer"]):
        element.decompose()
    lines = soup.get_text("\n", strip=True).split("\n")
    start = lines.index("Back") + 1 if "Back" in lines else 0
    end = lines.index("Status History") if "Status History" in lines else len(lines)
    fields, label = {}, None
    for line in lines[start:end]:
        if line.endswith(":") and len(line) < 40:
            label = line.rstrip(":").strip()
            fields[label] = []
        elif label:
            fields[label].append(line)
    history = []
    tail = lines[end:]
    for index, line in enumerate(tail[:-1]):
        following = tail[index + 1]
        if DATE.match(following) and not DATE.match(line) and line not in ("Status", "Date"):
            history.append({"status": line, "date": following})
    return {label: values for label, values in fields.items()}, history


def parse_date(value):
    match = DATE.search(value or "")
    return datetime.strptime(match.group(0), "%m/%d/%Y").date() if match else None


class CivilViewListingAdapter:
    def __init__(self, county_id, timeout=30):
        self.county_id, self.timeout = county_id, timeout

    def fetch(self):
        records = []
        with httpx.Client(headers=HEADERS, timeout=self.timeout, follow_redirects=True) as client:
            page = client.get(search_url(self.county_id))
            page.raise_for_status()
            if "Sales Listing" not in page.text and "SalesSearch" not in page.text:
                raise RuntimeError("CivilView search page not recognised")
            links = detail_links(page.text)
            missing = []
            for link in links:
                html = self._detail(client, link)
                if html is None:
                    missing.append(link)
                    continue
                fields, history = parse_detail(html)
                records.append({"detail_url": BASE + link, "fields": fields, "status_history": history})
        # A listing can be withdrawn between the search page and its details;
        # many missing details means the session broke, so fail instead.
        if len(missing) > max(5, len(links) // 20):
            raise RuntimeError(f"{len(missing)} of {len(links)} CivilView detail pages did not load")
        return records

    def _detail(self, client, link):
        # Long runs (Philadelphia has 1,500+ listings) can lose the session, which
        # redirects details to the home page; reload the search page and retry.
        for attempt in range(3):
            time.sleep(0.2)
            response = client.get(BASE + link)
            response.raise_for_status()
            if "Sales Listing Detail" in response.text:
                return response.text
            time.sleep(5 * (attempt + 1))
            client.get(search_url(self.county_id)).raise_for_status()
        return None
