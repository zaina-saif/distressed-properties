"""NY Supreme Court calendar PDFs -> case indices -> NYSCEF sale notices -> PostgreSQL.

Covers New York (Manhattan), Kings, Queens, Bronx, Richmond, Nassau, Suffolk,
Westchester, Orange, Onondaga and Erie (pipeline.queens.counties); Queens by default.
Each county is collected, then loaded, before the next starts.

Run on the operator machine. Unattended access challenges fail closed (exit 2).
--assisted permits only the human to complete challenges in visible Chrome.

    python -m pipeline.queens_foreclosure_refresh --assisted --county Nassau --county Suffolk --dry-run
    python -m pipeline.queens_foreclosure_refresh --assisted --county all
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import fcntl
import json
import logging
from pathlib import Path
import time
import uuid

from pipeline.queens.browser import AccessChallenge, CourtBrowser
from pipeline.queens.counties import COUNTIES, county as find_county
from pipeline.queens.parsing import QUEENS, digest, parse_notice

LOG = logging.getLogger(__name__)


def collect(browser, start, end, report, county=QUEENS):
    cases, calendar_urls = browser.calendars(start, end, county)
    report['cases'] = len(cases)
    records, review = [], []
    for case in cases:
        candidates = []
        for url in browser.notices(case, county):
            body, content = browser.pdf(url)
            row = parse_notice(content, case, url, digest(body), county)
            row['calendar_urls'] = calendar_urls
            candidates.append(row)
            report['notices'] += 1
        if not candidates:
            report['without_notice'] += 1
            continue
        # Duplicate filings can contain the same notice. Conflicting notices need
        # filing chronology/operator review; maximum date alone is not authority.
        unique = {(r['street'], r['city'], r['sale_date'], r['judgment_amount']) for r in candidates}
        if len(unique) > 1:
            for row in candidates:
                row['review_reasons'].append('multiple_conflicting_notices')
        if any(r['review_reasons'] for r in candidates):
            review.extend(candidates)
        else:
            records.append(candidates[0])
        time.sleep(1)
    report['review'] = len(review)
    report['accepted'] = len(records)
    return records, review


COUNTS = ('cases', 'notices', 'review', 'accepted', 'without_notice')


def collect_counties(browser, args, folder, report, loader):
    """Collect and load one county at a time; a later challenge leaves earlier counties loaded."""
    any_review = False
    for county in args.counties:
        part = {key: 0 for key in COUNTS}
        report['counties'][county.name] = part
        records, review = collect(browser, args.start, args.end, part, county)
        stem = county.name.lower().replace(' ', '-')
        (folder / f'snapshot-{stem}.json').write_text(json.dumps(records, indent=2))
        (folder / f'review-{stem}.json').write_text(json.dumps(review, indent=2))
        if not args.dry_run:
            if loader is None:
                from pipeline.queens.loading import load_records
                loader = load_records
            loaded = loader(records, county=county.name)
            part.update(loaded)
            for key, value in loaded.items():
                report[key] = report.get(key, 0) + value
        for key in COUNTS:
            report[key] += part[key]
        part['status'] = 'needs_review' if review else 'completed'
        any_review = any_review or bool(review)
    return any_review


def run(args, browser_factory=None, loader=None):
    args.run_dir.mkdir(parents=True, exist_ok=True)
    args.counties = getattr(args, 'counties', None) or [QUEENS]
    report = {'status': 'running', 'cases': 0, 'notices': 0, 'review': 0,
              'accepted': 0, 'without_notice': 0, 'dry_run': args.dry_run, 'counties': {},
              'started_at': datetime.now(timezone.utc).isoformat()}
    # Lock covers collection as well as loading; unique run folders prevent stale reuse.
    with (args.run_dir / 'refresh.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            LOG.error('Another NY court foreclosure refresh is active')
            return 1
        folder = args.run_dir / ('run-' + uuid.uuid4().hex)
        folder.mkdir(mode=0o700)
        handler = logging.FileHandler(folder / 'refresh.log')
        logging.getLogger().addHandler(handler)
        try:
            if browser_factory:
                any_review = collect_counties(browser_factory(folder), args, folder, report, loader)
            else:
                from pipeline.scraping.browser import BrowserManager
                from pipeline.scraping.config import ScrapingSettings
                from pipeline.scraping.monitoring import ScrapeMonitor
                settings = ScrapingSettings.from_env()
                settings.browser_channel, settings.operator_timeout = args.channel, args.operator_timeout
                # Shared launcher: same persistent profile, visible only when assisted,
                # screenshots/HTML of any challenge under the run folder.
                with BrowserManager('ny-queens-court', settings, assisted=args.assisted, profile_dir=args.profile,
                                    monitor=ScrapeMonitor(folder / 'artifacts')) as manager:
                    browser = CourtBrowser(manager.context, folder / 'pdfs', args.assisted, args.operator_timeout)
                    any_review = collect_counties(browser, args, folder, report, loader)
            report['status'] = 'needs_review' if any_review else 'completed'
            return 3 if any_review else 0
        except AccessChallenge:
            report['status'] = 'access_challenge'
            LOG.exception('Court requires operator assistance; nothing imported')
            return 2
        except Exception as exc:
            report['status'] = 'failed'
            report['error_type'] = type(exc).__name__
            LOG.exception('NY court foreclosure refresh failed')
            return 1
        finally:
            report['completed_at'] = datetime.now(timezone.utc).isoformat()
            (folder / 'report.json').write_text(json.dumps(report, indent=2))
            temp = args.run_dir / 'report.tmp'
            temp.write_text(json.dumps(report, indent=2))
            temp.replace(args.run_dir / 'report.json')
            logging.getLogger().removeHandler(handler)
            handler.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--county', action='append', default=[], metavar='NAME',
                        help=f"repeatable; one of {', '.join(c.name for c in COUNTIES.values())}, or all (default Queens)")
    parser.add_argument('--start', type=date.fromisoformat, default=date.today())
    parser.add_argument('--end', type=date.fromisoformat, default=date.today() + timedelta(days=30))
    parser.add_argument('--run-dir', type=Path, default=Path('../.local/queens-refresh'))
    parser.add_argument('--profile', type=Path, default=Path('../.local/queens-refresh-browser'))
    parser.add_argument('--channel', default='chrome')
    parser.add_argument('--assisted', action='store_true')
    parser.add_argument('--operator-timeout', type=int, default=600)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if args.end < args.start or (args.end - args.start).days > 90:
        parser.error('Calendar window must be between 0 and 90 days')
    try:
        names = [n for value in args.county for n in value.split(',') if n.strip()]
        args.counties = (list(COUNTIES.values()) if any(n.strip().lower() == 'all' for n in names)
                         else list(dict.fromkeys(find_county(n) for n in names)) or [QUEENS])
    except ValueError as exc:
        parser.error(str(exc))
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    raise SystemExit(run(args))


if __name__ == '__main__':
    main()
