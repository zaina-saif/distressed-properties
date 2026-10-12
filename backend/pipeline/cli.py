"""One command for every scraper (run from backend/):

    python main.py list                        # registered scrapers
    python main.py scrape nj                   # every statewide scraper for a state
    python main.py scrape county "bergen"      # scrapers covering one county
    python main.py scrape county "kings" --state NY
    python main.py scrape county "queens" --assisted   # visible browser for verification
    python main.py scrape ok --dry-run         # scrape only; load nothing

Each run writes monitoring artifacts (responses, snapshots, errors, command logs)
under SCRAPER_ARTIFACT_DIR (default .local/scrape-artifacts/) and records a
scrape_runs row per scraper. Exit code 0 when every scraper succeeded, 1 otherwise,
2 when a site needs operator verification.
"""
import argparse
import sys

from pipeline.scraping.base import DatabaseManager, RunContext, all_scrapers, find
from pipeline.scraping.challenge import AccessChallenge
from pipeline.scraping.config import ScrapingSettings
from pipeline.scraping.monitoring import ScrapeMonitor, configure_logging

ACCESS_CHALLENGE_EXIT = 2


def parse(argv=None):
    parser = argparse.ArgumentParser(prog="main.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="show registered scrapers")
    listing.add_argument("state", nargs="?")
    scrape = commands.add_parser("scrape", help="scrape a state, or one county with: scrape county NAME")
    scrape.add_argument("target", help='a state code (nj, ny, ...) or "county"')
    scrape.add_argument("county", nargs="?", help="county name when target is county")
    scrape.add_argument("--state", help="limit a county run to one state")
    scrape.add_argument("--dry-run", action="store_true", help="scrape and save snapshots only; load nothing")
    scrape.add_argument("--assisted", action="store_true",
                        help="visible browser; the operator completes any verification")
    scrape.add_argument("--no-record", action="store_true", help="do not write scrape_runs rows")
    args = parser.parse_args(argv)
    if args.command == "scrape":
        if args.target.lower() == "county":
            if not args.county:
                parser.error('scrape county needs a county name, e.g. scrape county "bergen"')
        elif args.county:
            parser.error("give either a state (scrape nj) or a county (scrape county NAME)")
    return args


def describe(scraper) -> str:
    scope = "statewide" if getattr(scraper, "statewide", True) else "county runs only"
    counties = list(scraper.counties)
    shown = "any" if "*" in counties else ", ".join(counties[:6]) + (f" (+{len(counties) - 6})" if len(counties) > 6 else "")
    browser = " [browser]" if scraper.requires_browser else ""
    return f"{scraper.state}  {scraper.name:<28} {scope:<16} counties: {shown}{browser}"


def main(argv=None, db: DatabaseManager | None = None) -> int:
    args = parse(argv)
    if args.command == "list":
        for scraper in sorted(all_scrapers(args.state), key=lambda s: (s.state, s.name)):
            print(describe(scraper))
        return 0

    county = args.county if args.target.lower() == "county" else None
    state = args.state.upper() if args.state else (None if county else args.target.upper())
    scrapers = find(state, county)
    if not scrapers:
        where = f"{county.title()} County" + (f", {state}" if state else "") if county else state
        print(f"No scraper covers {where}. `python main.py list` shows what is available.")
        return 1

    settings = ScrapingSettings.from_env()
    label = f"{state or ''}-{county or 'statewide'}".strip("-")
    monitor = ScrapeMonitor.for_run(settings.artifact_dir, label)
    log = configure_logging(monitor.run_dir)
    ctx = RunContext(settings, monitor, assisted=args.assisted, dry_run=args.dry_run)
    db = None if (args.no_record or args.dry_run) else (db or DatabaseManager())
    log.info("artifacts: %s", monitor.run_dir)

    exit_code = 0
    for scraper in scrapers:
        if scraper.requires_browser and not args.assisted:
            log.info("%s uses a browser; without --assisted it stops at any verification check", scraper.name)
        run_id = db.start(scraper.name, county, {"state": scraper.state, "artifacts": str(monitor.run_dir),
                                                  "dry_run": args.dry_run}) if db else None
        try:
            result = scraper.run(ctx, county)
            ok = result.get("ok", True)
            error = None
        except AccessChallenge as exc:
            monitor.error(scraper.name, exc)
            result, ok, error = {"access_challenge": exc.kind}, False, str(exc)
            exit_code = max(exit_code, ACCESS_CHALLENGE_EXIT)
        except Exception as exc:  # noqa: BLE001 - one scraper's failure must not stop the others
            monitor.error(scraper.name, exc)
            result, ok, error = {}, False, f"{type(exc).__name__}: {exc}"
        if not ok:
            exit_code = max(exit_code, 1)
        log.info("%s %s: %s%s", scraper.name, "ok" if ok else "FAILED", result, f" ({error})" if error else "")
        if db:
            db.finish(run_id, ok, result, error)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
