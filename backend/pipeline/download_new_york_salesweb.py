"""Visible, human-assisted downloader for the NY Sales Web portal.

This intentionally does not automate CAPTCHA. The operator completes challenges
in the visible browser, then the script resumes ordinary form entry/downloads.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout, sync_playwright


PORTAL_URL = "https://pad.tax.ny.gov/index"
NYC_COUNTIES = {"Bronx", "Kings", "New York", "Queens", "Richmond"}
COUNTIES = [
    "Albany", "Allegany", "Broome", "Cattaraugus", "Cayuga", "Chautauqua", "Chemung", "Chenango",
    "Clinton", "Columbia", "Cortland", "Delaware", "Dutchess", "Erie", "Essex", "Franklin", "Fulton",
    "Genesee", "Greene", "Hamilton", "Herkimer", "Jefferson", "Lewis", "Livingston", "Madison", "Monroe",
    "Montgomery", "Nassau", "Niagara", "Oneida", "Onondaga", "Ontario", "Orange", "Orleans", "Oswego",
    "Otsego", "Putnam", "Rensselaer", "Rockland", "St. Lawrence", "Saratoga", "Schenectady", "Schoharie",
    "Schuyler", "Seneca", "Steuben", "Suffolk", "Sullivan", "Tioga", "Tompkins", "Ulster", "Warren",
    "Washington", "Wayne", "Westchester", "Wyoming", "Yates",
]


@dataclass(frozen=True)
class Job:
    county: str
    year: int
    start_date: str
    end_date: str

    @property
    def key(self) -> str:
        return f"{self.county.lower().replace(' ', '_')}_{self.year}"


def jobs(counties: list[str], start_year: int, end_year: int, today: date | None = None) -> list[Job]:
    today = today or date.today()
    planned = []
    for county in counties:
        for year in range(start_year, end_year + 1):
            end = today if year == today.year else date(year, 12, 31)
            planned.append(Job(county, year, date(year, 1, 1).strftime("%m/%d/%Y"), end.strftime("%m/%d/%Y")))
    return planned


def load_checkpoint(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return set(json.loads(path.read_text()).get("completed", []))


def save_checkpoint(path: Path, completed: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"completed": sorted(completed)}, indent=2) + "\n")


def choose_combobox(page: Page, label: str, option_pattern: str) -> None:
    combo = page.get_by_role("combobox", name=re.compile(label, re.I)).first
    combo.click()
    page.get_by_role("option", name=re.compile(option_pattern, re.I)).first.click()


def fill_date_field(page: Page, label: str, value: str) -> None:
    field = page.get_by_role("textbox", name=re.compile(label, re.I)).first
    field.fill(value)


def prepare_search(page: Page, job: Job) -> None:
    clear = page.get_by_role("button", name=re.compile(r"^clear$", re.I))
    if clear.count():
        clear.first.click()
    choose_combobox(page, "County", rf"(?:\d+\s+)?{re.escape(job.county)} County")
    # SalesWeb normally auto-selects “All Municipalities” after county selection.
    page.get_by_role("button", name=re.compile("Criteria", re.I)).first.click()
    choose_combobox(page, "Criteria", "Sales Date Range")
    fill_date_field(page, "Start", job.start_date)
    fill_date_field(page, "End", job.end_date)
    add = page.get_by_role("button", name=re.compile(r"^(add|apply|save)$", re.I))
    if add.count():
        add.first.click()
    page.get_by_role("button", name=re.compile(r"^search$", re.I)).first.click()
    page.get_by_text(re.compile(r"Download Search Results", re.I)).wait_for(timeout=120_000)


def download_results(page: Page, job: Job, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    with page.expect_download(timeout=120_000) as download_info:
        page.get_by_text(re.compile(r"Download Search Results", re.I)).first.click()
    download = download_info.value
    suffix = Path(download.suggested_filename).suffix or ".xlsx"
    destination = output_dir / f"ny_salesweb_{job.key}{suffix.lower()}"
    download.save_as(destination)
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description="Human-assisted official NY SalesWeb downloads")
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--counties", nargs="+", choices=COUNTIES)
    scope.add_argument("--all-counties", action="store_true")
    parser.add_argument("--start-year", type=int, default=2020)
    parser.add_argument("--end-year", type=int, default=date.today().year)
    parser.add_argument("--output-dir", type=Path, default=Path("data/public/ny_salesweb"))
    parser.add_argument("--profile-dir", type=Path, default=Path("../.local/ny-salesweb-browser"))
    parser.add_argument("--checkpoint", type=Path, default=Path("data/public/ny_salesweb/checkpoint.json"))
    parser.add_argument("--delay", type=float, default=3.0)
    parser.add_argument("--browser-channel", default="chrome")
    parser.add_argument("--manual-search", action="store_true",
                        help="Pause for the operator to set each search; automate only downloads/checkpoints")
    args = parser.parse_args()
    if args.start_year > args.end_year:
        parser.error("--start-year cannot exceed --end-year")

    selected = COUNTIES if args.all_counties else args.counties
    planned = jobs(selected, args.start_year, args.end_year)
    completed = load_checkpoint(args.checkpoint)
    args.profile_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(args.profile_dir.resolve()), channel=args.browser_channel, headless=False,
            accept_downloads=True, viewport={"width": 1500, "height": 1000},
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(PORTAL_URL, wait_until="domcontentloaded", timeout=120_000)
        input("Complete the CAPTCHA and open Real Property Sales Search. Press Enter here when ready: ")

        for index, job in enumerate(planned, 1):
            if job.key in completed:
                print(f"[{index}/{len(planned)}] skip completed {job.key}", flush=True)
                continue
            print(f"[{index}/{len(planned)}] {job.county} {job.start_date}–{job.end_date}", flush=True)
            if args.manual_search:
                input(f"Set {job.county}, {job.start_date}–{job.end_date}, run Search, then press Enter: ")
                saved = download_results(page, job, args.output_dir)
                completed.add(job.key)
                save_checkpoint(args.checkpoint, completed)
                print(f"saved {saved}", flush=True)
                time.sleep(max(args.delay, 0))
                continue
            try:
                prepare_search(page, job)
                body = page.locator("body").inner_text()
                if re.search(r"limited to (?:20|50)k|refine your search", body, re.I):
                    print(f"Result limit reached for {job.key}; split this year into quarters manually.", flush=True)
                    input("Refine the visible search and run it. Press Enter when Download Search Results appears: ")
                saved = download_results(page, job, args.output_dir)
            except PlaywrightTimeout:
                print("Portal did not reach the expected state. Complete any CAPTCHA or the search manually.", flush=True)
                input(f"Set {job.county}, {job.start_date}–{job.end_date}, run Search, then press Enter: ")
                saved = download_results(page, job, args.output_dir)
            completed.add(job.key)
            save_checkpoint(args.checkpoint, completed)
            print(f"saved {saved}", flush=True)
            time.sleep(max(args.delay, 0))
        context.close()


if __name__ == "__main__":
    main()
