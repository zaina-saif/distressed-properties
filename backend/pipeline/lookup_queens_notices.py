"""Find the NYSCEF Notice of Sale for Queens foreclosure-auction cases (operator-assisted).

Input is the calendar saved by collect_webcivil_calendar (index numbers, auction dates).
A visible browser searches NYSCEF as a guest for each case; the operator completes any
CAPTCHA or check, and the script then finds the Notice of Sale, downloads it and parses
the premises, auction date and judgment. Results are written to the run folder only;
nothing is loaded.

    python -m pipeline.lookup_queens_notices --calendar .local/webcivil/<run>/queens_auction_calendar.json --cases 3
"""
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from pipeline.queens.browser import AccessChallenge, CourtBrowser, LayoutChanged
from pipeline.queens.parsing import digest, parse_notice
from pipeline.scraping.browser import BrowserManager
from pipeline.scraping.config import BACKEND, ScrapingSettings
from pipeline.scraping.monitoring import ScrapeMonitor

OUTPUT = BACKEND.parent / ".local" / "queens-notices"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--calendar", type=Path, required=True)
    parser.add_argument("--cases", type=int, default=3, help="how many cases to look up, in calendar order")
    parser.add_argument("--index", nargs="+", help="specific index numbers instead")
    parser.add_argument("--delay", type=float, default=4.0)
    parser.add_argument("--profile", type=Path, default=BACKEND.parent / ".local" / "webcivil-browser")
    args = parser.parse_args()

    calendar = json.loads(args.calendar.read_text())
    upcoming = [row for row in calendar if not row.get("outcome")]
    chosen = [row for row in upcoming if row["index_number"] in set(args.index)] if args.index else upcoming[:args.cases]
    run_dir = OUTPUT / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir.mkdir(parents=True, exist_ok=True)
    monitor = ScrapeMonitor(run_dir / "artifacts")
    settings = ScrapingSettings.from_env()
    settings.browser_channel = settings.browser_channel or "chrome"
    results = []
    with BrowserManager("ny-webcivil", settings, assisted=True, profile_dir=args.profile, monitor=monitor) as manager:
        court = CourtBrowser(manager.context, run_dir / "pdfs", assisted=True, operator_timeout=settings.operator_timeout)
        for row in chosen:
            case = row["index_number"]
            result = {"index_number": case, "calendar_date": row["auction_date"], "status": None, "notices": []}
            try:
                for url in court.notices(case):
                    body, text = court.pdf(url)
                    notice = parse_notice(text, case, url, digest(body))
                    notice.pop("raw_text", None)
                    result["notices"].append(notice)
                result["status"] = "found" if result["notices"] else "no_notice_of_sale"
            except AccessChallenge as exc:
                result["status"] = f"access_challenge: {exc}"
                results.append(result)
                print(f"{case}: stopped, {exc}", flush=True)
                break
            except (LayoutChanged, ValueError, RuntimeError) as exc:
                result["status"] = f"{type(exc).__name__}: {exc}"
                monitor.snapshot(f"{case.replace('/', '-')}-{type(exc).__name__}", page=court.page)
            results.append(result)
            print(f"{case}: {result['status']}" + "".join(
                f" | {n['street']}, {n['city']} {n['zip_code'] or ''} sale {n['sale_date']} judgment {n['judgment_amount']}"
                f"{' REVIEW ' + ','.join(n['review_reasons']) if n['review_reasons'] else ''}" for n in result["notices"]), flush=True)
            (run_dir / "results.json").write_text(json.dumps(results, indent=1))
            time.sleep(args.delay)
    print(f"results: {run_dir / 'results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
