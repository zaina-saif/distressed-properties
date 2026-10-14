"""Operator-assisted capture of NY WebCivil calendar pages (iapps.courts.state.ny.us).

WebCivil answers scripts with a Cloudflare check, so this opens a visible browser: the
operator completes the check, then the script saves the calendar page and follows the
WebCivil links on it (further calendar pages and case details), one page every few
seconds in the same session. Nothing is solved or bypassed; if the check comes back the
script waits for the operator again, and stops when they do not respond.

    python -m pipeline.collect_webcivil_calendar --url "https://iapps.courts.state.ny.us/webcivil/FCASCalendarDetail?..."

Pages are saved under .local/webcivil/<run>/ for pipeline.load_webcivil_calendar.
"""
import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from pipeline.scraping.browser import BrowserManager
from pipeline.scraping.challenge import AccessChallenge
from pipeline.scraping.config import BACKEND, ScrapingSettings
from pipeline.scraping.monitoring import ScrapeMonitor, slug

HOST = "iapps.courts.state.ny.us"
OUTPUT = BACKEND.parent / ".local" / "webcivil"
# WebCivil pages worth following from a calendar: more calendar pages and case details.
FOLLOW = re.compile(r"/webcivil/(FCASCalendarDetail|FCAS(?:Case|Appearance)\w*|CaseInfo\w*)", re.I)


def webcivil_links(base_url: str, hrefs: list[str]) -> list[str]:
    links = []
    for href in hrefs:
        url = urljoin(base_url, href or "")
        parts = urlsplit(url)
        if parts.scheme == "https" and parts.hostname == HOST and FOLLOW.search(parts.path) and url != base_url:
            links.append(url.split("#")[0])
    return list(dict.fromkeys(links))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", action="append", required=True, help="WebCivil calendar URL (repeatable)")
    parser.add_argument("--max-pages", type=int, default=150)
    parser.add_argument("--delay", type=float, default=4.0, help="seconds between pages")
    parser.add_argument("--profile", type=Path, default=BACKEND.parent / ".local" / "webcivil-browser")
    args = parser.parse_args()

    run_dir = OUTPUT / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    pages_dir = run_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    settings = ScrapingSettings.from_env()
    settings.browser_channel = settings.browser_channel or "chrome"
    settings.domain_delays = {**settings.domain_delays, HOST: args.delay}
    queue, seen, index = list(dict.fromkeys(args.url)), set(), []
    with BrowserManager("ny-webcivil", settings, assisted=True, profile_dir=args.profile,
                        monitor=ScrapeMonitor(run_dir / "artifacts")) as browser:
        try:
            while queue and len(seen) < args.max_pages:
                url = queue.pop(0)
                if url in seen:
                    continue
                seen.add(url)
                browser.goto(url)
                html = browser.page.content()
                name = f"{len(seen):03d}-{slug(urlsplit(url).path.rsplit('/', 1)[-1])}.html"
                (pages_dir / name).write_text(html, encoding="utf-8")
                index.append({"file": name, "url": url, "title": browser.page.title(),
                              "saved_at": datetime.now(timezone.utc).isoformat()})
                hrefs = browser.page.eval_on_selector_all("a[href]", "nodes => nodes.map(n => n.getAttribute('href'))")
                new = [link for link in webcivil_links(browser.page.url, hrefs) if link not in seen]
                queue.extend(link for link in new if link not in queue)
                print(f"saved {name} ({len(new)} new links, {len(queue)} queued)", flush=True)
                time.sleep(args.delay)
        except AccessChallenge as exc:
            print(f"Stopped: {exc}", flush=True)
        finally:
            (run_dir / "index.json").write_text(json.dumps(index, indent=1))
    print(f"{len(index)} pages saved in {run_dir}")
    return 0 if index else 2


if __name__ == "__main__":
    raise SystemExit(main())
