"""Saved browser sessions (Playwright storage state: cookies and local storage),
one file per site under settings.session_dir with owner-only permissions.

A session saved after the operator passed a site's verification is reused until
it expires; the browser manager notices an expired one when the site shows its
challenge again, and only then asks the operator to verify again. Session files
hold login-equivalent cookies: they stay in .local/ and are never committed."""
import json
import os
import time
from pathlib import Path

from pipeline.scraping.monitoring import slug


class SessionManager:
    def __init__(self, session_dir: Path, max_age_hours: float = 24.0, clock=time.time):
        self.session_dir = Path(session_dir)
        self.max_age_seconds = max_age_hours * 3600
        self.clock = clock

    def path(self, site: str) -> Path:
        return self.session_dir / f"{slug(site)}.json"

    def state(self, site: str) -> dict | None:
        path = self.path(site)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            return None

    def is_fresh(self, site: str) -> bool:
        """A saved session not older than max_age with at least one unexpired cookie
        (session cookies, expires -1, count as unexpired)."""
        state = self.state(site)
        if not state or self.clock() - self.path(site).stat().st_mtime > self.max_age_seconds:
            return False
        now = self.clock()
        return any(cookie.get("expires", -1) in (-1, None) or cookie["expires"] > now
                   for cookie in state.get("cookies", []))

    def storage_state(self, site: str) -> str | None:
        """Path to pass as Playwright's storage_state, or None to start a fresh session."""
        return str(self.path(site)) if self.is_fresh(site) else None

    def save(self, context, site: str) -> Path:
        self.session_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self.path(site)
        temp = path.with_suffix(".tmp")
        context.storage_state(path=str(temp))
        os.chmod(temp, 0o600)
        temp.replace(path)
        return path

    def invalidate(self, site: str) -> None:
        self.path(site).unlink(missing_ok=True)
