"""Per-host pacing, robots.txt policy and retry backoff."""
import random
import threading
import time
import urllib.robotparser
from collections.abc import Callable
from urllib.parse import urlsplit

from pipeline.scraping.challenge import detect_challenge
from pipeline.scraping.config import ScrapingSettings


class RateLimiter:
    """At most one request per `delay_for(host)` seconds to each host (thread-safe).
    A robots.txt Crawl-delay larger than the configured delay wins."""

    def __init__(self, settings: ScrapingSettings, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.settings, self.clock, self.sleep = settings, clock, sleep
        self.last: dict[str, float] = {}
        self.minimums: dict[str, float] = {}
        self.lock = threading.Lock()

    def set_minimum(self, host: str, seconds: float) -> None:
        self.minimums[host.lower()] = seconds

    def wait(self, url: str) -> float:
        host = (urlsplit(url).hostname or "").lower()
        delay = max(self.settings.delay_for(host), self.minimums.get(host, 0.0))
        with self.lock:
            now = self.clock()
            ready = self.last.get(host, now - delay) + delay
            pause = max(0.0, ready - now)
            self.last[host] = now + pause
        if pause:
            self.sleep(pause)
        return pause


class RobotsPolicy:
    """robots.txt per host, following RFC 9309: an unavailable file (4xx) allows
    everything; an unreachable one (5xx or network error) disallows everything. A
    verification page served instead of the file (a Cloudflare 403, say) is not "no
    robots.txt": the site would not let the file be read, so it counts as unreachable."""

    def __init__(self, fetch: Callable[[str], tuple[int, str]], user_agent: str = "*"):
        self.fetch, self.user_agent = fetch, user_agent
        self.parsers: dict[str, urllib.robotparser.RobotFileParser | bool] = {}

    def _parser(self, url: str):
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self.parsers:
            try:
                status, body = self.fetch(origin + "/robots.txt")
            except Exception:  # noqa: BLE001 - unreachable robots.txt means disallow
                status, body = 503, ""
            if status in (401, 403, 429) and detect_challenge(body, status) in ("cloudflare", "captcha", "bot_protection"):
                self.parsers[origin] = False
            elif 400 <= status < 500:
                self.parsers[origin] = True
            elif status >= 500:
                self.parsers[origin] = False
            else:
                parser = urllib.robotparser.RobotFileParser()
                parser.parse(body.splitlines())
                self.parsers[origin] = parser
        return self.parsers[origin]

    def allowed(self, url: str) -> bool:
        parser = self._parser(url)
        return parser if isinstance(parser, bool) else parser.can_fetch(self.user_agent, url)

    def crawl_delay(self, url: str) -> float | None:
        parser = self._parser(url)
        if isinstance(parser, bool):
            return None
        delay = parser.crawl_delay(self.user_agent)
        return float(delay) if delay is not None else None


def backoff_delay(attempt: int, base: float = 2.0, cap: float = 60.0, jitter: float = 0.1) -> float:
    """Exponential backoff for retry `attempt` (1, 2, 3, ...): base**attempt seconds,
    capped, with a little jitter so parallel workers do not retry in step."""
    delay = min(cap, base ** attempt)
    return delay + random.uniform(0, delay * jitter)


RETRYABLE_STATUS = {429, 500, 502, 503, 504}
