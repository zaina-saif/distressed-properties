"""Visible, operator-assisted collector for Queens County foreclosure sales.

The court sites (WebCivil Supreme calendars and NYSCEF) answer scripts with a
Cloudflare check, and NYSCEF guest search has a CAPTCHA. This runner never
solves either: it opens a visible Chrome window, the operator passes the check,
and the script only works inside that session. See AGENTS.md (New York pipeline).

    python -m pipeline.collect_queens_foreclosures --discover

--discover opens WebCivil and NYSCEF in tabs and records every page the operator
visits (HTML) and every PDF opened or downloaded, until the window is closed.
The saved files are the fixtures the calendar and notice parsers are built on.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError, sync_playwright

WEBCIVIL_CALENDAR_URL = "https://iapps.courts.state.ny.us/webcivil/FCASCalendarSearch"
NYSCEF_SEARCH_URL = "https://iapps.courts.state.ny.us/nyscef/CaseSearch"
QUEENS_COURT_CODE = "80"
CACHE = Path("../.local/nyc-queens-court")
PROFILE = Path("../.local/nyc-queens-court-browser")


def is_challenge(title: str, html: str) -> bool:
    return "just a moment" in title.lower() or "challenges.cloudflare.com" in html[:5000]


def slug(url: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", url.split("://", 1)[-1])[:90].strip("_")


class Recorder:
    """Saves visited pages and PDFs, with a manifest of what came from where."""

    def __init__(self, folder: Path):
        self.folder = folder
        (folder / "pages").mkdir(parents=True, exist_ok=True)
        (folder / "pdfs").mkdir(parents=True, exist_ok=True)
        self.manifest = folder / "manifest.jsonl"
        self.count = 0

    def note(self, kind: str, url: str, path: Path) -> None:
        self.count += 1
        entry = {"kind": kind, "url": url, "file": str(path), "saved_at": datetime.now(timezone.utc).isoformat()}
        with self.manifest.open("a") as handle:
            handle.write(json.dumps(entry) + "\n")
        print(f"saved {kind}: {path.name}  <- {url[:120]}", flush=True)

    def page_loaded(self, page) -> None:
        try:
            html, title, url = page.content(), page.title(), page.url
        except PlaywrightError:
            return
        if is_challenge(title, html):
            print("Cloudflare/CAPTCHA check showing: complete it in the browser window.", flush=True)
            return
        path = self.folder / "pages" / f"{datetime.now():%H%M%S}_{slug(url)}.html"
        path.write_text(html)
        self.note("page", url, path)

    def response(self, response) -> None:
        if "application/pdf" not in (response.headers.get("content-type") or ""):
            return
        try:
            body = response.body()
        except PlaywrightError:
            return
        if not body.startswith(b"%PDF-"):
            return
        path = self.folder / "pdfs" / f"{datetime.now():%H%M%S}_{slug(response.url)}.pdf"
        path.write_bytes(body)
        self.note("pdf", response.url, path)

    def download(self, download) -> None:
        path = self.folder / "pdfs" / f"{datetime.now():%H%M%S}_{download.suggested_filename}"
        download.save_as(path)
        self.note("download", download.url, path)


def discover(profile: Path, channel: str) -> None:
    folder = CACHE / "discovery" / datetime.now().strftime("%Y%m%d-%H%M%S")
    recorder = Recorder(folder)
    print(f"Recording to {folder}", flush=True)
    print("In the browser: pass the check, search the Queens (court 80) foreclosure calendar in WebCivil,\n"
          "then in NYSCEF open 3-5 of those cases and open each 'Notice of Sale'. Close the window when done.",
          flush=True)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(profile.resolve()), channel=channel, headless=False, accept_downloads=True)

        def watch(page):
            page.on("load", lambda: recorder.page_loaded(page))
            page.on("download", recorder.download)

        context.on("page", watch)
        context.on("response", recorder.response)
        for page in context.pages:
            watch(page)
        first = context.pages[0] if context.pages else context.new_page()
        first.goto(WEBCIVIL_CALENDAR_URL)
        context.new_page().goto(NYSCEF_SEARCH_URL)
        # Keep recording until the operator closes every tab.
        while context.pages:
            try:
                context.pages[0].wait_for_timeout(1000)
            except PlaywrightError:
                time.sleep(0.5)
        context.close()
    print(f"Done: {recorder.count} files in {folder}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--discover", action="store_true", help="Record pages and PDFs while the operator browses")
    parser.add_argument("--profile-dir", type=Path, default=PROFILE)
    parser.add_argument("--browser-channel", default="chrome")
    args = parser.parse_args()
    if not args.discover:
        parser.error("Only --discover is available until the calendar and notice formats are captured.")
    PROFILE.parent.mkdir(parents=True, exist_ok=True)
    discover(args.profile_dir, args.browser_channel)


if __name__ == "__main__":
    main()
