"""Scrape Indiana sheriff foreclosure sales from SRI Services (see adapters/sri.py).

    python -m pipeline.scrape_sri --all                                   # upcoming sales
    python -m pipeline.scrape_sri --counties Marion "St Joseph"
    python -m pipeline.scrape_sri --all --lookback-days 14                # and last two weeks' results
    python -m pipeline.scrape_sri --all --history-from 2025-10-01         # past results only, to history/

Each listing is saved with its case detail (judgment, plaintiff, minimum bid and,
once sold, the price). A --history-from run covers past sale days only and writes
to history/, which load_sri_sales --history loads without retiring current listings.
"""
import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from pipeline.adapters.sri import SITE_URL, SriClient

OUTPUT = Path("data/sheriff_sales/sri")
PARSER_VERSION = "sri_v1"
STATE = "IN"


def snapshot_path(county, history=False):
    name = f"{STATE.lower()}_{county.lower().replace(' ', '_')}.json"
    return OUTPUT / "history" / name if history else OUTPUT / name


def scrape(county, start, end=None, history=False):
    client = SriClient()
    try:
        items = []
        for listing in client.listings(STATE, county, start, end):
            items.append({"listing": listing, "detail": client.detail(listing)})
    finally:
        client.close()
    snapshot = {"state": STATE, "county": county, "source_url": SITE_URL, "parser_version": PARSER_VERSION,
                "scraped_at": datetime.now(timezone.utc).isoformat(), "start": start.isoformat(),
                "end": end.isoformat() if end else None, "items": items}
    path = snapshot_path(county, history)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=1) + "\n")
    return len(items)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--counties", nargs="+")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--lookback-days", type=int, default=0,
                        help="Also include sale days in the last N days, so their results are loaded")
    parser.add_argument("--history-from", type=date.fromisoformat,
                        help="Past sale days from this date to yesterday, written to history/ (results only)")
    args = parser.parse_args()
    client = SriClient()
    known = client.counties(STATE)
    client.close()
    counties = known if args.all else args.counties or []
    unknown = [county for county in counties if county not in known]
    if unknown:
        parser.error(f"Unknown {STATE} counties: {', '.join(unknown)}")
    today = date.today()
    if args.history_from:
        start, end = args.history_from, today - timedelta(days=1)
    else:
        start, end = today - timedelta(days=args.lookback_days), None
    failed = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(scrape, county, start, end, bool(args.history_from)): county for county in counties}
        for future in as_completed(futures):
            county = futures[future]
            try:
                print(f"{STATE} {county}: {future.result()} listings", flush=True)
            except Exception as exc:  # noqa: BLE001 - one county must not stop the rest
                # The previous snapshot is kept, so a failed county is never loaded as empty.
                print(f"{STATE} {county}: FAILED, previous snapshot kept ({type(exc).__name__}: {exc})", flush=True)
                failed.append(county)
    if failed:
        raise SystemExit(f"Failed counties: {', '.join(sorted(failed))}")


if __name__ == "__main__":
    main()
