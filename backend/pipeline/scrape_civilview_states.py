"""Scrape CivilView SalesWeb listings for counties outside New Jersey.

New Jersey counties use scrape_nj_civilview and load_to_supabase. Ohio and
Florida counties that are also on RealAuction are collected there instead.

    python -m pipeline.scrape_civilview_states --all
    python -m pipeline.scrape_civilview_states --counties "DE:New Castle" "PA:Philadelphia"
"""
import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from pipeline.adapters.civilview_listing import CivilViewListingAdapter, search_url

OUTPUT = Path("data/sheriff_sales/civilview")
PARSER_VERSION = "civilview_listing_v1"
# (state, county) -> CivilView county ids; Texas counties list each constable
# precinct and the sheriff separately.
COUNTIES = {
    ("DE", "New Castle"): [24], ("DE", "Kent"): [4], ("DE", "Sussex"): [12],
    ("PA", "Philadelphia"): [60], ("PA", "Montgomery"): [23], ("PA", "Lehigh"): [51],
    ("IL", "Lake"): [58], ("IL", "Champaign"): [42],
    ("GA", "Coweta"): [92],
    ("TX", "Dallas"): [93, 94, 95, 96, 97], ("TX", "Guadalupe"): [86, 87, 88, 89, 90],
    ("TX", "McLennan"): [76, 77, 78, 79, 80], ("TX", "Rockwall"): [69, 70, 71, 72, 63],
}


def key(state, county):
    return f"{state}:{county}"


def snapshot_path(state, county):
    return OUTPUT / f"{state.lower()}_{county.lower().replace(' ', '_')}.json"


def scrape(state, county):
    records = []
    for county_id in COUNTIES[(state, county)]:
        for record in CivilViewListingAdapter(county_id).fetch():
            records.append({**record, "county_id": county_id})
    snapshot_path(state, county).write_text(json.dumps({
        "state": state, "county": county, "source_urls": [search_url(i) for i in COUNTIES[(state, county)]],
        "parser_version": PARSER_VERSION, "scraped_at": datetime.now(timezone.utc).isoformat(),
        "records": records}, indent=1) + "\n")
    return len(records)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--counties", nargs="+", choices=sorted(key(*item) for item in COUNTIES))
    parser.add_argument("--state", help="All configured counties in one state")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.all:
        targets = sorted(COUNTIES)
    elif args.state:
        targets = sorted(item for item in COUNTIES if item[0] == args.state.upper())
    else:
        targets = [tuple(value.split(":", 1)) for value in args.counties or []]
    OUTPUT.mkdir(parents=True, exist_ok=True)
    failed = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(scrape, state, county): (state, county) for state, county in targets}
        for future in as_completed(futures):
            state, county = futures[future]
            try:
                print(f"{state} {county}: {future.result()} listings", flush=True)
            except Exception as exc:  # noqa: BLE001 - keep the previous snapshot
                print(f"{state} {county}: FAILED, previous snapshot kept ({type(exc).__name__}: {exc})", flush=True)
                failed.append(key(state, county))
    if failed:
        raise SystemExit(f"Failed counties: {', '.join(sorted(failed))}")


if __name__ == "__main__":
    main()
