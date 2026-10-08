"""Scrape Connecticut's statewide list of pending foreclosure-by-sale auctions.

The Judicial Branch lists pending sales by town; each sale has a public notice
with the case caption, docket, sale date and the property address. These are
court-ordered auctions run by a court-appointed committee, not sheriff sales.

    python -m pipeline.scrape_ct_foreclosure_sales

The server only negotiates older TLS ciphers (AES256-SHA256), so the client
allows them while still verifying the certificate.
"""
import json
import re
import ssl
import time
from datetime import datetime, timezone
from html import unescape
from pathlib import Path

import certifi
import httpx

BASE = "https://sso.eservices.jud.ct.gov/foreclosures/Public/"
TOWN_LIST = BASE + "PendPostbyTownList.aspx"
OUTPUT = Path("data/sheriff_sales/ct_foreclosure_sales.json")
PARSER_VERSION = "ct_foreclosure_sales_v1"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"}


def client():
    context = ssl.create_default_context(cafile=certifi.where())
    context.set_ciphers("DEFAULT:AES256-SHA256:AES128-SHA256:@SECLEVEL=1")
    return httpx.Client(verify=context, headers=HEADERS, timeout=30, follow_redirects=True)


def text_of(html):
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())


def town_links(html):
    return list(dict.fromkeys(link.strip() for link in re.findall(r'href="(PendPostbyTownDetails\.aspx\?Town=[^"]+)"', html)))


def town_sales(html):
    """Rows of a town page: sale date, docket, sale type and address text, notice link."""
    sales = []
    for row in re.findall(r"(?s)<tr[^>]*>(.*?)</tr>", re.sub(r"(?s)<(script|style)[^>]*>.*?</\1>", "", html)):
        cells = re.findall(r"(?s)<td[^>]*>(.*?)</td>", row)
        link = re.search(r'href="(PendPostDetailPublic\.aspx\?PostingId=(\d+))"', row)
        if len(cells) < 4 or not link:
            continue
        sales.append({"posting_id": link.group(2), "notice_url": BASE + link.group(1),
                      "sale_date": text_of(cells[1]), "docket": text_of(cells[2]), "listing": text_of(cells[3])})
    return sales


def notice_fields(html):
    """Label/value pairs from a notice ("Case Caption:", "TOWN:", "SALE DATE:" ...) plus its text."""
    body = re.sub(r"(?s)<(script|style)[^>]*>.*?</\1>", "", html)
    lines = [line.strip() for line in unescape(re.sub(r"<[^>]+>", "\n", body)).split("\n") if line.strip()]
    fields = {}
    for index, line in enumerate(lines[:-1]):
        if line.endswith(":") and len(line) < 40 and line[:-1] not in fields:
            fields[line[:-1].strip()] = lines[index + 1]
    deposit = re.search(r"in the amount of \$\s*([\d,]+(?:\.\d+)?)", " ".join(lines))
    fields["deposit"] = deposit.group(1) if deposit else None
    return fields


def scrape():
    records = []
    with client() as http:
        towns = town_links(http.get(TOWN_LIST).text)
        if not towns:
            raise RuntimeError("Connecticut town list returned no towns")
        for town_link in towns:
            town = town_link.split("Town=", 1)[1].strip()
            for sale in town_sales(http.get(BASE + town_link).text):
                time.sleep(0.2)
                notice = notice_fields(http.get(sale["notice_url"]).text)
                records.append({**sale, "town": town, "notice": notice})
    return records


def main():
    records = scrape()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps({"state": "CT", "source_url": TOWN_LIST, "parser_version": PARSER_VERSION,
                                  "scraped_at": datetime.now(timezone.utc).isoformat(), "records": records}, indent=1) + "\n")
    print(f"CT: {len(records)} pending foreclosure sales saved to {OUTPUT}")


if __name__ == "__main__":
    main()
