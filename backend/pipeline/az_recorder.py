"""Arizona county recorders: trustee-sale recordings and their documents.

A county is configured in data/az_trustee_sale_sources.json (recorder API, document codes,
parcel layer, pacing); docs/arizona/maricopa-recorder.md explains the Maricopa endpoints.

- RecorderIndex: the recorder's public JSON search (publicapi.recorder.maricopa.gov), one
  document code at a time, a week per query (the API stops counting at 500), 200 rows a page.
  Party names come back with every row and are dropped here, never stored.
- DocumentFetcher: the document PDFs. The recorder serves them only through the website's
  "Unofficial PDF" link, so they are fetched in a real, undisguised Chrome (BrowserManager)
  on the operator's machine: the page asks the API for the preview link exactly as the
  site's button does, then downloads it. A verification check stops a headless run and
  waits for the operator in an --assisted one. PDFs are cached by recording number in
  .local/az-recorder/<county>/pdf/, so each document is fetched once.
"""
import dataclasses
import json
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from pathlib import Path

from pipeline.scraping.config import ScrapingSettings
from pipeline.scraping.http import PoliteClient, RobotsDisallowed

CONFIG = Path(__file__).resolve().parents[1] / "data" / "az_trustee_sale_sources.json"
LOCAL = Path(__file__).resolve().parents[2] / ".local" / "az-recorder"
KINDS = ("notice", "cancellation", "trustee_deed")


@dataclasses.dataclass
class CountyConfig:
    name: str
    recorder: dict
    parcels: dict
    settings: dict

    @property
    def slug(self) -> str:
        return self.name.lower().replace(" ", "-")

    @property
    def cache(self) -> Path:
        return LOCAL / self.slug

    def scraping_settings(self) -> ScrapingSettings:
        return dataclasses.replace(ScrapingSettings.from_env(),
                                   default_delay=float(self.settings["request_delay_seconds"]))


def county_config(name: str, path: Path = CONFIG) -> CountyConfig:
    config = json.loads(path.read_text())
    for county, entry in config["counties"].items():
        if county.lower() == name.lower():
            return CountyConfig(county, entry["recorder"], entry["parcels"],
                                {**config["defaults"], **entry.get("settings", {})})
    raise SystemExit(f"{name}: not in {path.name} (configured: {', '.join(config['counties'])})")


def weeks(start: date, end: date, days: int) -> Iterator[tuple[date, date]]:
    """Inclusive windows of `days` days covering start..end."""
    while start <= end:
        stop = min(start + timedelta(days=days - 1), end)
        yield start, stop
        start = stop + timedelta(days=1)


def index_row(row: dict, kind: str) -> dict:
    """The fields kept from a search row; `names` (the parties) is left out."""
    return {"recording_number": str(row["recordingNumber"]) + (row.get("recordingSuffix") or ""),
            "recording_date": datetime.strptime(row["recordingDate"], "%m-%d-%Y").date().isoformat(),
            "document_code": row["documentCode"], "kind": kind}


class RecorderIndex:
    def __init__(self, county: CountyConfig, client: PoliteClient):
        self.county, self.client = county, client
        self.api = county.recorder["api"]

    def search(self, kind: str, start: date, end: date) -> list[dict]:
        code = self.county.recorder["document_codes"][kind]
        size = int(self.county.settings["page_size"])
        rows, page = [], 1
        while True:
            response = self.client.get(f"{self.api}/documents/search", params={
                "documentCode": code, "beginDate": start.isoformat(), "endDate": end.isoformat(),
                "pageNumber": page, "pageSize": size})
            response.raise_for_status()
            found = response.json().get("searchResults") or []
            rows += [index_row(row, kind) for row in found]
            if len(found) < size:
                return rows
            page += 1

    def recordings(self, start: date, end: date, kinds=KINDS) -> list[dict]:
        found = {}
        for kind in kinds:
            for first, last in weeks(start, end, int(self.county.settings["window_days"])):
                for row in self.search(kind, first, last):
                    found[row["recording_number"]] = row
        return sorted(found.values(), key=lambda row: row["recording_number"])

    def page_count(self, recording_number: str) -> int | None:
        response = self.client.get(f"{self.api}/documents/{recording_number}")
        return response.json().get("pageAmount") if response.status_code == 200 else None


class DocumentFetcher:
    """Opens the county's document search page once, then fetches each PDF through it."""

    def __init__(self, county: CountyConfig, assisted: bool = False):
        self.county, self.assisted = county, assisted
        self.folder = county.cache / "pdf"
        self.browser = None
        self.robots_client = PoliteClient(county.scraping_settings())

    def path(self, recording_number: str) -> Path:
        return self.folder / f"{recording_number}.pdf"

    def __enter__(self) -> "DocumentFetcher":
        from pipeline.scraping.browser import BrowserManager

        self.folder.mkdir(parents=True, exist_ok=True)
        self.browser = BrowserManager(f"{self.county.slug}-recorder", settings=self.county.scraping_settings(),
                                      assisted=self.assisted,
                                      profile_dir=LOCAL.parent / "browser-profiles" / f"{self.county.slug}-recorder")
        self.browser.__enter__()
        self.browser.goto(self.county.recorder["website"])
        return self

    def __exit__(self, *exc) -> None:
        self.robots_client.close()
        self.browser.__exit__(*exc)

    def allowed(self, url: str) -> str:
        """The URL a preview link finally serves from, each hop checked against its host's robots.txt.
        Maricopa's preview redirects to legacy.recorder.maricopa.gov/recdocdata/, which that host's
        robots.txt disallows, so this raises there."""
        for _ in range(5):
            if not self.robots_client.robots.allowed(url):
                raise RobotsDisallowed(f"robots.txt disallows {url.split('?')[0]}")
            self.browser.limiter.wait(url)
            response = self.browser.context.request.get(url, max_redirects=0, timeout=120_000)
            if response.status not in (301, 302, 303, 307, 308):
                return url
            url = response.headers["location"]
        raise RuntimeError(f"too many redirects for {url}")

    def fetch(self, recording_number: str) -> Path | None:
        """The cached PDF, fetching it when missing; None when the recorder has no preview."""
        target = self.path(recording_number)
        if target.exists() and target.stat().st_size:
            return target
        number, suffix = recording_number[:11], recording_number[11:]
        link_url = (f"{self.county.recorder['api']}/preview/pdf-link?recordingNumber={number}"
                    f"&suffix={suffix}&affidavit=false")
        self.browser.limiter.wait(link_url)
        link = self.browser.page.evaluate(
            "async (u) => { const r = await fetch(u); return {status: r.status, body: await r.text()}; }", link_url)
        if link["status"] != 200:
            if link["status"] in (401, 403) and "not available" not in link["body"]:
                self.browser.ensure_access()
            return None
        url = self.allowed(json.loads(link["body"])["url"])
        self.browser.limiter.wait(url)
        response = self.browser.context.request.get(url, timeout=120_000)
        if response.status != 200 or not response.body().startswith(b"%PDF"):
            return None
        target.write_bytes(response.body())
        return target
