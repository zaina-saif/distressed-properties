import json
import os
from datetime import date

import httpx
import pytest

from pipeline.scraping.base import CommandScraper, RunContext, SaleRecord, find, matches
from pipeline.scraping.browser import BrowserManager
from pipeline.scraping.challenge import AccessChallenge, detect_challenge
from pipeline.scraping.config import ScrapingSettings
from pipeline.scraping.http import PoliteClient, RobotsDisallowed
from pipeline.scraping.monitoring import ScrapeMonitor
from pipeline.scraping.rate_limit import RateLimiter, RobotsPolicy, backoff_delay
from pipeline.scraping.sessions import SessionManager


# --- challenge detection -------------------------------------------------------

@pytest.mark.parametrize("html,kind", [
    ("<html><head><title>Just a moment...</title></head><body></body></html>", "cloudflare"),
    ("<html><head><title>Attention Required! | Cloudflare</title></head></html>", "cloudflare"),
    ('<html><body><form id="challenge-form" action="/?__cf_chl_f_tk=1"><div class="cf-chl-widget"></div></form></body></html>', "cloudflare"),
    ("<HTML><HEAD><TITLE>Access Denied</TITLE></HEAD><BODY>errors.edgesuite.net</BODY></HTML>", "access_denied"),
    ("<html><head><title>403 - Forbidden</title></head></html>", "access_denied"),
    ("<html><body><p>Please verify you are a human to continue.</p></body></html>", "captcha"),
])
def test_challenge_pages(html, kind):
    assert detect_challenge(html) == kind


@pytest.mark.parametrize("html", [
    # Content pages that merely carry a CAPTCHA library or a protection script.
    '<html><head><title>Sheriff Sales</title><script src="https://www.google.com/recaptcha/api.js?render=x"></script></head>'
    '<body><table><tr><td>10/13/2026</td><td>26CV389</td></tr></table>This site is protected by reCAPTCHA.</body></html>',
    '<html><body><div class="h-captcha" data-size="invisible"></div><a href="calendar.pdf">Calendar</a></body></html>',
    '<html><head><script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script></head><body>Listings</body></html>',
])
def test_ordinary_pages_are_not_challenges(html):
    assert detect_challenge(html, 200) is None


def test_a_bare_403_with_little_text_is_access_denied_but_429_is_not_a_challenge():
    assert detect_challenge("<html><body>Forbidden</body></html>", 403) == "access_denied"
    assert detect_challenge("<html><body>Too many requests</body></html>", 429) is None


# --- rate limiting, robots, backoff ---------------------------------------------

def test_rate_limiter_paces_each_host_separately():
    now, slept = [100.0], []
    limiter = RateLimiter(ScrapingSettings(default_delay=2, domain_delays={"slow.gov": 5}),
                          clock=lambda: now[0], sleep=lambda s: (slept.append(s), now.__setitem__(0, now[0] + s)))
    limiter.wait("https://a.com/1")
    limiter.wait("https://a.com/2")
    limiter.wait("https://b.com/1")
    limiter.wait("https://www.slow.gov/x")
    limiter.wait("https://www.slow.gov/y")
    assert slept == [2.0, 5.0]


def test_robots_policy_follows_rfc_9309():
    files = {"https://a.com/robots.txt": (200, "User-agent: *\nDisallow: /private\nCrawl-delay: 4\n"),
             "https://b.com/robots.txt": (404, ""), "https://c.com/robots.txt": (503, "")}
    robots = RobotsPolicy(lambda url: files[url])
    assert robots.allowed("https://a.com/sales") and not robots.allowed("https://a.com/private/x")
    assert robots.crawl_delay("https://a.com/") == 4.0
    assert robots.allowed("https://b.com/anything")  # no robots.txt: allowed
    assert not robots.allowed("https://c.com/anything")  # unreachable: disallowed


def test_backoff_grows_and_is_capped():
    assert 2 <= backoff_delay(1, 2, 60, jitter=0) <= 2
    assert backoff_delay(3, 2, 60, jitter=0) == 8
    assert backoff_delay(10, 2, 60, jitter=0) == 60


# --- PoliteClient ---------------------------------------------------------------

def client_for(handler, tmp_path, **settings):
    options = {"default_delay": 0, "max_retries": 2, **settings}
    return PoliteClient(ScrapingSettings(**options), ScrapeMonitor(tmp_path), sleep=lambda _: None,
                        transport=httpx.MockTransport(handler))


def test_polite_client_retries_transient_errors_then_succeeds(tmp_path):
    calls = []

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        calls.append(request.url.path)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, text="ok")

    with client_for(handler, tmp_path) as client:
        assert client.get("https://x.gov/list").text == "ok"
    assert len(calls) == 3
    log = [json.loads(line) for line in (tmp_path / "responses.jsonl").read_text().splitlines()]
    assert [entry["status"] for entry in log if entry["url"].endswith("/list")] == [503, 503, 200]


def test_polite_client_stops_on_a_challenge_without_retrying(tmp_path):
    calls = []

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        calls.append(1)
        return httpx.Response(403, headers={"content-type": "text/html"},
                              text="<html><head><title>Just a moment...</title></head></html>")

    with client_for(handler, tmp_path) as client, pytest.raises(AccessChallenge) as raised:
        client.get("https://x.gov/list")
    assert raised.value.kind == "cloudflare" and len(calls) == 1
    assert list(tmp_path.glob("*challenge-cloudflare.html"))


def test_polite_client_honours_robots(tmp_path):
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /\n")
        raise AssertionError("a disallowed page was fetched")

    with client_for(handler, tmp_path) as client, pytest.raises(RobotsDisallowed):
        client.get("https://x.gov/list")


def test_monitor_never_writes_cookies(tmp_path):
    monitor = ScrapeMonitor(tmp_path)
    monitor.response("https://x.gov", 200, {"Set-Cookie": "secret=1", "Content-Type": "text/html"})
    text = (tmp_path / "responses.jsonl").read_text()
    assert "secret" not in text and "text/html" in text


# --- sessions and the browser manager -------------------------------------------

class FakeContext:
    def __init__(self, cookies):
        self.cookies, self.pages, self.closed = cookies, [], False

    def storage_state(self, path):
        open(path, "w").write(json.dumps({"cookies": self.cookies, "origins": []}))

    def new_page(self):
        page = FakePage()
        self.pages.append(page)
        return page

    def close(self):
        self.closed = True


def test_sessions_are_saved_privately_and_expire(tmp_path):
    now = [1_000_000.0]
    sessions = SessionManager(tmp_path, max_age_hours=1, clock=lambda: now[0])
    path = sessions.save(FakeContext([{"name": "cf", "expires": now[0] + 600}]), "court site")
    assert path.name == "court-site.json" and oct(os.stat(path).st_mode)[-3:] == "600"
    os.utime(path, (now[0], now[0]))
    assert sessions.storage_state("court site") == str(path)
    now[0] += 700  # the cookie expired
    assert sessions.storage_state("court site") is None
    sessions.invalidate("court site")
    assert not path.exists()


class FakePage:
    url = "https://court.test/search"

    def __init__(self):
        self.challenged = ["captcha", "captcha", None]

    def goto(self, url, **_):
        return None


class FakePlaywright:
    def __init__(self, context):
        self.context = context
        self.chromium = self

    def __call__(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def launch(self, **_):
        return self

    def new_context(self, **_):
        return self.context

    def close(self):
        return None


def manager(tmp_path, assisted, notes):
    context = FakeContext([{"name": "cf", "expires": -1}])
    settings = ScrapingSettings(default_delay=0, operator_timeout=30, session_dir=tmp_path / "sessions")
    return BrowserManager("court", settings, assisted=assisted, monitor=None, notifier=notes.append,
                          detector=lambda page: page.challenged.pop(0) if page.challenged else None,
                          playwright_factory=FakePlaywright(context), sleep=lambda _: None)


def test_assisted_run_waits_for_the_operator_then_saves_the_session(tmp_path):
    notes = []
    with manager(tmp_path, True, notes) as browser:
        browser.goto("https://court.test/search")
    assert len(notes) == 1 and "court" in notes[0]
    assert (tmp_path / "sessions" / "court.json").exists()


def test_headless_run_stops_at_a_challenge(tmp_path):
    notes = []
    with pytest.raises(AccessChallenge, match="--assisted"):
        with manager(tmp_path, False, notes) as browser:
            browser.goto("https://court.test/search")
    assert notes == [] and not (tmp_path / "sessions" / "court.json").exists()


# --- records, registry and CLI --------------------------------------------------

def test_sale_record_maps_to_the_shared_loader():
    sale = SaleRecord("1 Main St", "Tulsa", "OK", "74103", date(2026, 11, 4), "CJ-1", "Tulsa", "https://x",
                      plaintiff="Bank", minimum_bid=5000.0).to_sale()
    assert (sale.case, sale.street, sale.zip_code, sale.upset, sale.plaintiff) == ("CJ-1", "1 Main St", "74103", 5000.0, "Bank")


def test_registry_lookup_by_state_and_county():
    names = {scraper.name for scraper in find("NJ")}
    assert names == {"nj-sale-refresh"}  # the county plugin only runs for a named county
    assert {scraper.name for scraper in find(None, "bergen")} == {"nj-civilview-county"}
    assert {scraper.name for scraper in find("OK", "tulsa")} == {"ok-county-sale-lists"}
    assert find(None, "albany") == []  # "*" sources (Indiana SRI) need the state named
    assert {scraper.name for scraper in find("IN", "marion")} == {"in-sri"}
    assert matches("Bergen", ["bergen"]) and not matches("x", ["*"]) and matches("x", ["*"], True)


def test_command_steps_for_a_county_and_a_dry_run(tmp_path):
    scraper = next(s for s in find(None, "bergen"))
    ctx = RunContext(ScrapingSettings(), ScrapeMonitor(tmp_path))
    assert scraper.commands("bergen", ctx) == [["pipeline.scrape_nj_civilview", "--counties", "Bergen", "--load"],
                                               ["pipeline.create_properties"]]
    ctx.dry_run = True
    assert scraper.commands("bergen", ctx) == [["pipeline.scrape_nj_civilview", "--counties", "Bergen"]]
    queens = next(s for s in find("NY", "queens") if s.requires_browser)
    ctx.assisted = True
    assert queens.commands("queens", ctx) == [["pipeline.queens_foreclosure_refresh", "--county", "Queens", "--assisted", "--dry-run"]]
    nassau = next(s for s in find("NY", "nassau") if s.requires_browser)
    assert nassau.commands("nassau", ctx) == [["pipeline.queens_foreclosure_refresh", "--county", "Nassau", "--assisted", "--dry-run"]]


def test_cli_reports_an_uncovered_county(capsys):
    from pipeline.cli import main
    assert main(["scrape", "county", "albany"]) == 1
    assert "No scraper covers Albany County" in capsys.readouterr().out


def test_cli_runs_scrapers_and_records_jobs(tmp_path, monkeypatch):
    from pipeline import cli
    from pipeline.scraping import base

    ran, recorded = [], []
    fake = CommandScraper(name="zz-test", state="ZZ", counties=["Test"],
                          scrape=lambda counties, ctx: ["pipeline.nothing"])
    fake.run = lambda ctx, county=None: ran.append(county) or {"ok": True, "records": 3}
    monkeypatch.setattr(base, "REGISTRY", [fake])
    monkeypatch.setattr(cli, "find", lambda state, county: [s for s in base.REGISTRY if s.covers(state, county)])
    monkeypatch.setenv("SCRAPER_ARTIFACT_DIR", str(tmp_path))

    class DB:
        def start(self, name, county, meta):
            recorded.append(("start", name, county))
            return "run-1"

        def finish(self, run_id, ok, result, error=None):
            recorded.append(("finish", run_id, ok, result["records"]))

    assert cli.main(["scrape", "county", "test"], db=DB()) == 0
    assert ran == ["test"] and recorded == [("start", "zz-test", "test"), ("finish", "run-1", True, 3)]
