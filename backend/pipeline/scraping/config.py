"""Scraping settings from the environment (backend/.env; see .env.example)."""
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND / ".env")

DEFAULT_USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")


@dataclass
class ScrapingSettings:
    user_agent: str = DEFAULT_USER_AGENT
    # Seconds between requests to one host, and per-host overrides ({"tinstar.io": 2}).
    default_delay: float = 1.0
    domain_delays: dict[str, float] = field(default_factory=dict)
    max_retries: int = 3
    backoff_base: float = 2.0
    backoff_cap: float = 60.0
    respect_robots: bool = True
    # One fixed outbound proxy (for example a company egress proxy). There is
    # deliberately no rotation or per-site proxy pool: those exist to avoid a
    # site's own limits, which this framework does not do.
    proxy_url: str | None = None
    headless: bool = True
    browser_channel: str | None = None
    operator_timeout: int = 600
    session_dir: Path = BACKEND.parent / ".local" / "sessions"
    artifact_dir: Path = BACKEND.parent / ".local" / "scrape-artifacts"

    @classmethod
    def from_env(cls) -> "ScrapingSettings":
        env = os.environ.get
        return cls(
            user_agent=env("SCRAPER_USER_AGENT") or DEFAULT_USER_AGENT,
            default_delay=float(env("SCRAPER_DEFAULT_DELAY") or 1.0),
            domain_delays={host.lower(): float(delay)
                           for host, delay in json.loads(env("SCRAPER_DOMAIN_DELAYS") or "{}").items()},
            max_retries=int(env("SCRAPER_MAX_RETRIES") or 3),
            respect_robots=(env("SCRAPER_RESPECT_ROBOTS") or "1") != "0",
            proxy_url=env("SCRAPER_PROXY_URL") or None,
            headless=(env("SCRAPER_HEADLESS") or "1") != "0",
            browser_channel=env("SCRAPER_BROWSER_CHANNEL") or None,
            operator_timeout=int(env("SCRAPER_OPERATOR_TIMEOUT") or 600),
            session_dir=Path(env("SCRAPER_SESSION_DIR") or cls.session_dir),
            artifact_dir=Path(env("SCRAPER_ARTIFACT_DIR") or cls.artifact_dir),
        )

    def delay_for(self, host: str) -> float:
        host = host.lower()
        for domain, delay in self.domain_delays.items():
            if host == domain or host.endswith("." + domain):
                return delay
        return self.default_delay
