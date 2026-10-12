"""Monitoring artifacts for a scrape run: response metadata, HTML snapshots,
screenshots and error logs, under <artifact_dir>/<run>/.

Cookies, authorization and other credential headers are never written."""
import json
import logging
import re
import traceback
from datetime import datetime, timezone
from pathlib import Path

SAFE_HEADERS = {"content-type", "content-length", "server", "date", "last-modified", "location",
                "retry-after", "cache-control", "cf-ray", "x-cache"}


def slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-")[:80] or "page"


class ScrapeMonitor:
    def __init__(self, run_dir: Path):
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.count = 0

    @classmethod
    def for_run(cls, artifact_dir: Path, name: str) -> "ScrapeMonitor":
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return cls(Path(artifact_dir) / f"{stamp}-{slug(name)}")

    def _append(self, name: str, entry: dict) -> None:
        with (self.run_dir / name).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, default=str) + "\n")

    def response(self, url: str, status: int | None, headers: dict | None = None,
                 elapsed: float | None = None, note: str | None = None) -> None:
        kept = {key.lower(): value for key, value in (headers or {}).items() if key.lower() in SAFE_HEADERS}
        self._append("responses.jsonl", {"at": datetime.now(timezone.utc).isoformat(), "url": url,
                                         "status": status, "elapsed": elapsed, "headers": kept, "note": note})

    def snapshot(self, label: str, html: str | None = None, page=None) -> Path:
        """Save the HTML (and a full-page screenshot when a Playwright page is given)."""
        self.count += 1
        stem = self.run_dir / f"{self.count:03d}-{slug(label)}"
        if page is not None:
            try:
                html = html if html is not None else page.content()
                page.screenshot(path=str(stem.with_suffix(".png")), full_page=True)
            except Exception as exc:  # noqa: BLE001 - a failed capture must not stop the run
                logging.getLogger(__name__).warning("screenshot failed: %s", exc)
        if html is not None:
            stem.with_suffix(".html").write_text(html, encoding="utf-8")
        return stem

    def error(self, where: str, exc: BaseException) -> None:
        self._append("errors.jsonl", {"at": datetime.now(timezone.utc).isoformat(), "where": where,
                                      "error": f"{type(exc).__name__}: {exc}",
                                      "traceback": traceback.format_exception(exc)})


def configure_logging(run_dir: Path | None = None, level: int = logging.INFO) -> logging.Logger:
    """Console logging, plus <run_dir>/scrape.log when a run directory is given."""
    logger = logging.getLogger("scraping")
    logger.setLevel(level)
    if not any(isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler)
               for handler in logger.handlers):
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S"))
        logger.addHandler(console)
    if run_dir is not None:
        Path(run_dir).mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(Path(run_dir) / "scrape.log")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
    return logger
