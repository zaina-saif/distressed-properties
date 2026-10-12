"""PoliteClient: an httpx.Client that paces requests per host, honours robots.txt,
retries transient failures with exponential backoff, and stops on a verification
challenge instead of retrying around it.

It is a drop-in replacement where scrapers already take an httpx.Client."""
import logging
import time

import httpx

from pipeline.scraping.challenge import AccessChallenge, detect_challenge
from pipeline.scraping.config import ScrapingSettings
from pipeline.scraping.monitoring import ScrapeMonitor
from pipeline.scraping.rate_limit import RETRYABLE_STATUS, RateLimiter, RobotsPolicy, backoff_delay

LOG = logging.getLogger("scraping.http")


class RobotsDisallowed(RuntimeError):
    pass


class PoliteClient(httpx.Client):
    def __init__(self, settings: ScrapingSettings | None = None, monitor: ScrapeMonitor | None = None,
                 sleep=time.sleep, **kwargs):
        self.settings = settings or ScrapingSettings.from_env()
        self.monitor, self.sleep = monitor, sleep
        headers = {"User-Agent": self.settings.user_agent,
                   "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                   "Accept-Language": "en-US,en;q=0.9", **(kwargs.pop("headers", None) or {})}
        if self.settings.proxy_url and "proxy" not in kwargs and "transport" not in kwargs:
            kwargs["proxy"] = self.settings.proxy_url
        kwargs.setdefault("timeout", 60)
        kwargs.setdefault("follow_redirects", True)
        super().__init__(headers=headers, **kwargs)
        self.limiter = RateLimiter(self.settings, sleep=sleep)
        self.robots = RobotsPolicy(self._fetch_robots, "*")

    def _fetch_robots(self, url: str) -> tuple[int, str]:
        self.limiter.wait(url)
        response = super().send(self.build_request("GET", url))
        return response.status_code, response.text

    def send(self, request: httpx.Request, **kwargs) -> httpx.Response:
        url = str(request.url)
        if self.settings.respect_robots:
            if not self.robots.allowed(url):
                raise RobotsDisallowed(f"robots.txt disallows {url}")
            if (delay := self.robots.crawl_delay(url)) is not None:
                self.limiter.set_minimum(request.url.host, delay)
        attempt = 0
        while True:
            self.limiter.wait(url)
            started = time.monotonic()
            try:
                response = super().send(request, **kwargs)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                attempt += 1
                if attempt > self.settings.max_retries:
                    if self.monitor:
                        self.monitor.error(url, exc)
                    raise
                LOG.warning("%s on %s; retry %s", type(exc).__name__, url, attempt)
                self.sleep(backoff_delay(attempt, self.settings.backoff_base, self.settings.backoff_cap))
                continue
            if self.monitor:
                self.monitor.response(url, response.status_code, dict(response.headers), time.monotonic() - started)
            if self._is_html(response):
                response.read()
                kind = detect_challenge(response.text, response.status_code)
                if kind:
                    if self.monitor:
                        self.monitor.snapshot(f"challenge-{kind}", response.text)
                    raise AccessChallenge(f"{kind} challenge at {url}; a person must open it in a browser",
                                          kind, url)
            if response.status_code in RETRYABLE_STATUS and attempt < self.settings.max_retries:
                attempt += 1
                retry_after = response.headers.get("retry-after", "")
                wait = float(retry_after) if retry_after.isdigit() else backoff_delay(
                    attempt, self.settings.backoff_base, self.settings.backoff_cap)
                LOG.warning("HTTP %s from %s; retry %s in %.0fs", response.status_code, url, attempt, wait)
                response.close()
                self.sleep(min(wait, self.settings.backoff_cap))
                continue
            return response

    @staticmethod
    def _is_html(response: httpx.Response) -> bool:
        return "html" in response.headers.get("content-type", "").lower()
