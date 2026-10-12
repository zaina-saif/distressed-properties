"""Scraper plugins and the registry the CLI runs.

Two kinds of plugin:
  ScraperBase     a native scraper: fetch() returns SaleRecords (the common record
                  shape), loaded through sale_listing_loader.load_sales.
  CommandScraper  an existing scrape/load module pair run as `python -m ...`, so
                  every current source is reachable from the same CLI.
"""
import subprocess
import sys
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from pipeline.scraping.browser import BrowserManager
from pipeline.scraping.config import BACKEND, ScrapingSettings
from pipeline.scraping.http import PoliteClient
from pipeline.scraping.monitoring import ScrapeMonitor


@dataclass
class SaleRecord:
    """The common shape every native scraper returns."""
    property_address: str
    city: str | None
    state: str
    zip: str | None
    sale_date: date | None
    auction_id: str  # unique per county and source (case, sheriff or auction number)
    county: str
    source_url: str
    plaintiff: str | None = None
    defendant: str | None = None
    status: str = "scheduled"
    judgment: float | None = None
    minimum_bid: float | None = None
    attorney: str | None = None
    parcel: str | None = None
    raw: dict = field(default_factory=dict)

    def to_sale(self):
        from pipeline.sale_listing_loader import Sale
        return Sale(case=self.auction_id, street=self.property_address, city=self.city, zip_code=self.zip,
                    sale_date=self.sale_date, status=self.status, raw=self.raw or {"auction_id": self.auction_id},
                    parcel=self.parcel, upset=self.minimum_bid, judgment=self.judgment, plaintiff=self.plaintiff,
                    defendant=self.defendant, attorney=self.attorney)


@dataclass
class RunContext:
    settings: ScrapingSettings
    monitor: ScrapeMonitor
    assisted: bool = False
    dry_run: bool = False

    def client(self, **kwargs) -> PoliteClient:
        return PoliteClient(self.settings, self.monitor, **kwargs)

    def browser(self, site: str, profile_dir: Path | None = None) -> BrowserManager:
        return BrowserManager(site, self.settings, assisted=self.assisted, profile_dir=profile_dir,
                              monitor=self.monitor)


def matches(county: str | None, counties: Sequence[str], state_given: bool = False) -> bool:
    """A named county is in the list; "*" (the source discovers its own counties)
    matches any name, but only when the state was given too."""
    if county is None:
        return True
    if "*" in counties:
        return state_given
    return county.strip().lower() in {name.lower() for name in counties}


class ScraperBase(ABC):
    name: str
    state: str
    counties: Sequence[str]
    source_system: str
    source_url: str
    requires_browser = False

    def covers(self, state: str | None = None, county: str | None = None) -> bool:
        return (state is None or state.upper() == self.state) and matches(county, self.counties, state is not None)

    @abstractmethod
    def fetch(self, ctx: RunContext, county: str | None = None) -> list[SaleRecord]:
        """Every listed sale (for one county, or all of this scraper's counties)."""

    def run(self, ctx: RunContext, county: str | None = None) -> dict:
        records = self.fetch(ctx, county)
        result = {"records": len(records)}
        if ctx.dry_run:
            return result
        from pipeline.sale_listing_loader import load_sales
        by_county: dict[str, list[SaleRecord]] = {}
        for record in records:
            by_county.setdefault(record.county, []).append(record)
        for name, group in sorted(by_county.items()):
            result[name] = load_sales(self.state, name, self.source_system, self.source_url,
                                      [record.to_sale() for record in group], job=self.name)
        return result


@dataclass
class CommandScraper:
    """An existing module pair; `scrape(counties, ctx)`/`load(counties, ctx)` return module
    args, with counties None for all of them. `after` runs once the load succeeds.
    counties ("*",) accepts any county name in the state (the source discovers them)."""
    name: str
    state: str
    counties: Sequence[str]
    scrape: Callable[[list[str] | None, "RunContext"], list[str]]
    load: Callable[[list[str] | None, "RunContext"], list[str]] | None = None
    after: list[list[str]] = field(default_factory=list)
    county_level: bool = True  # can run for one named county
    statewide: bool = True  # part of `scrape <state>`
    requires_browser: bool = False

    def covers(self, state: str | None = None, county: str | None = None) -> bool:
        if county is None:
            return (state is None or state.upper() == self.state) and self.statewide
        return ((state is None or state.upper() == self.state) and self.county_level
                and matches(county, self.counties, state is not None))

    def commands(self, county: str | None, ctx: "RunContext") -> list[list[str]]:
        selected = None
        if county is not None:
            named = [name for name in self.counties if name.lower() == county.strip().lower()]
            selected = named or [county.strip().title()]
        steps = [self.scrape(selected, ctx)]
        if not ctx.dry_run:
            steps += ([self.load(selected, ctx)] if self.load else []) + list(self.after)
        return steps

    def run(self, ctx: RunContext, county: str | None = None) -> dict:
        log = ctx.monitor.run_dir / "commands.log"
        exits = []
        for args in self.commands(county, ctx):
            with log.open("a", encoding="utf-8") as handle:
                handle.write(f"\n===== {self.name}: python -m {' '.join(args)}\n")
                handle.flush()
                code = subprocess.run([sys.executable, "-m", *args], cwd=BACKEND, stdout=handle,
                                      stderr=subprocess.STDOUT).returncode
            exits.append({"command": " ".join(args), "exit_code": code})
            if code:
                break
        return {"steps": exits, "ok": all(step["exit_code"] == 0 for step in exits)}


REGISTRY: list = []


def register(scraper):
    REGISTRY.append(scraper)
    return scraper


def find(state: str | None = None, county: str | None = None) -> list:
    from pipeline.scraping import plugins  # noqa: F401 - registers every plugin
    return [scraper for scraper in REGISTRY if scraper.covers(state, county)]


def all_scrapers(state: str | None = None) -> list:
    from pipeline.scraping import plugins  # noqa: F401
    return [scraper for scraper in REGISTRY if state is None or scraper.state == state.upper()]


class DatabaseManager:
    """Records each CLI run of a scraper in scrape_runs (the job history)."""

    def __init__(self, engine=None):
        if engine is None:
            from app.database.session import engine as default_engine
            engine = default_engine
        self.engine = engine

    def start(self, name: str, county: str | None, metadata: dict) -> str:
        from sqlalchemy import text
        run_id = str(uuid.uuid4())
        with self.engine.begin() as connection:
            connection.execute(text("""INSERT INTO scrape_runs(id,job_name,county,source_system,started_at,status,
                execution_metadata) VALUES(:id,:job,:county,'scraping_cli',:now,'running',CAST(:meta AS JSONB))"""),
                {"id": run_id, "job": f"cli:{name}", "county": county, "now": datetime.now(timezone.utc),
                 "meta": _json(metadata)})
        return run_id

    def finish(self, run_id: str, ok: bool, result: dict, error: str | None = None) -> None:
        from sqlalchemy import text
        with self.engine.begin() as connection:
            connection.execute(text("""UPDATE scrape_runs SET completed_at=NOW(), status=:status,
                records_found=COALESCE(:found, records_found), error_message=:error,
                execution_metadata=COALESCE(execution_metadata,'{}'::jsonb) || CAST(:meta AS JSONB) WHERE id=:id"""),
                {"id": run_id, "status": "completed" if ok else "failed", "found": result.get("records"),
                 "error": error, "meta": _json({"result": result})})


def _json(value) -> str:
    import json
    return json.dumps(value, default=str)
