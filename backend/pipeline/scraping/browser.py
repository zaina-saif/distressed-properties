"""BrowserManager: Playwright Chromium with saved sessions, per-host pacing,
monitoring snapshots and the manual verification workflow.

When a page is a verification challenge:
  - assisted (visible browser): notify the operator, wait until they complete it,
    save the session, and continue;
  - headless: stop with AccessChallenge (rerun with --assisted). Nothing is retried
    around the challenge.

The browser is not disguised: no stealth patches, automation flags left as they
are, the real browser's own user agent. A site that keeps challenging an automated
browser after the operator passed is declining automation; use a manual export.
"""
import logging
import platform
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from pipeline.scraping.challenge import AccessChallenge, detect_challenge
from pipeline.scraping.config import ScrapingSettings
from pipeline.scraping.monitoring import ScrapeMonitor
from pipeline.scraping.rate_limit import RateLimiter
from pipeline.scraping.sessions import SessionManager

LOG = logging.getLogger("scraping.browser")


def notify_operator(message: str) -> None:
    """Terminal message and bell, plus a macOS notification when available."""
    print(f"\a\n>>> OPERATOR: {message}\n", flush=True)
    if platform.system() == "Darwin":
        safe = message.replace('"', "'")
        subprocess.run(["osascript", "-e", f'display notification "{safe}" with title "Sheriff Sale Hunter"'],
                       check=False, capture_output=True, timeout=10)


def page_challenge(page) -> str | None:
    try:
        return detect_challenge(page.content(), title=page.title())
    except Exception:  # noqa: BLE001 - mid-navigation pages cannot be read yet
        return "navigating"


class BrowserManager:
    def __init__(self, site: str, settings: ScrapingSettings | None = None, assisted: bool = False,
                 profile_dir: Path | None = None, monitor: ScrapeMonitor | None = None,
                 sessions: SessionManager | None = None, notifier: Callable[[str], None] = notify_operator,
                 detector: Callable[[object], str | None] = page_challenge, accept_downloads: bool = True,
                 playwright_factory=None, sleep=time.sleep):
        self.site = site
        self.settings = settings or ScrapingSettings.from_env()
        # Verification needs a person at a visible window.
        self.assisted = assisted
        self.headless = False if assisted else self.settings.headless
        self.profile_dir, self.monitor = profile_dir, monitor
        self.sessions = sessions or SessionManager(self.settings.session_dir)
        self.notifier, self.detector, self.sleep = notifier, detector, sleep
        self.accept_downloads = accept_downloads
        self.playwright_factory = playwright_factory
        self.limiter = RateLimiter(self.settings, sleep=sleep)
        self.playwright = self.browser = self.context = self.page = None

    def __enter__(self) -> "BrowserManager":
        if self.playwright_factory is None:
            from playwright.sync_api import sync_playwright
            self.playwright_factory = sync_playwright
        self._manager = self.playwright_factory()
        self.playwright = self._manager.__enter__()
        options = {"headless": self.headless}
        if self.settings.browser_channel:
            options["channel"] = self.settings.browser_channel
        if self.settings.proxy_url:
            options["proxy"] = {"server": self.settings.proxy_url}
        if self.profile_dir:
            Path(self.profile_dir).mkdir(parents=True, exist_ok=True)
            self.context = self.playwright.chromium.launch_persistent_context(
                str(Path(self.profile_dir).resolve()), accept_downloads=self.accept_downloads, **options)
        else:
            self.browser = self.playwright.chromium.launch(**options)
            self.context = self.browser.new_context(storage_state=self.sessions.storage_state(self.site),
                                                    accept_downloads=self.accept_downloads)
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is None and self.context is not None and not self.profile_dir:
                self.sessions.save(self.context, self.site)
        finally:
            if self.context is not None:
                self.context.close()
            if self.browser is not None:
                self.browser.close()
            self._manager.__exit__(exc_type, exc, tb)

    def goto(self, url: str, wait_until: str = "domcontentloaded", timeout: int = 60_000):
        self.limiter.wait(url)
        response = self.page.goto(url, wait_until=wait_until, timeout=timeout)
        if self.monitor:
            self.monitor.response(url, response.status if response else None,
                                  dict(response.headers) if response else None)
        self.ensure_access()
        return response

    def ensure_access(self) -> None:
        """Return when the current page is not a challenge; otherwise wait for the
        operator (assisted) or stop (headless)."""
        kind = self.detector(self.page)
        if kind in (None, "navigating"):
            return
        if self.monitor:
            self.monitor.snapshot(f"challenge-{kind}", page=self.page)
        if not self.assisted:
            self.sessions.invalidate(self.site)
            raise AccessChallenge(f"{self.site}: {kind} verification required; rerun with --assisted "
                                  "and complete it in the browser window", kind, self.page.url)
        self.wait_for_operator(kind)

    def wait_for_operator(self, kind: str) -> None:
        self.notifier(f"{self.site} shows a {kind} check. Complete it in the browser window; "
                      f"the run continues by itself (waiting up to {self.settings.operator_timeout // 60} min).")
        deadline = time.monotonic() + self.settings.operator_timeout
        while time.monotonic() < deadline:
            self.sleep(1)
            if self.detector(self.page) is None:
                LOG.info("%s: verification passed; saving the session", self.site)
                if not self.profile_dir:
                    self.sessions.save(self.context, self.site)
                if self.monitor:
                    self.monitor.response(self.page.url, None, note="operator verification passed")
                return
        raise AccessChallenge(f"{self.site}: the operator did not complete the {kind} check in time",
                              kind, self.page.url)

    def snapshot(self, label: str) -> None:
        if self.monitor:
            self.monitor.snapshot(label, page=self.page)
