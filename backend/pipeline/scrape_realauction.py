"""Scrape upcoming foreclosure auctions from RealAuction county sites.

Ohio: county sheriff sales on *.sheriffsaleauction.ohio.gov.
Florida: clerk foreclosure sales on www.*.realforeclose.com.
Colorado: Public Trustee foreclosure sales on *.realforeclose.com.
Texas: sheriff and constable property-tax foreclosure sales on *.texas.sheriffsaleauctions.com
and *.texas.realforeclose.com.

    python -m pipeline.scrape_realauction --state OH --all
    python -m pipeline.scrape_realauction --state FL --counties "Miami-Dade" Broward
    python -m pipeline.scrape_realauction --state TX --all --from-date 2026-10-06   # include a sale just held
"""
import argparse
import json
from datetime import date
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from pipeline.adapters.realauction import RealAuctionAdapter

OUTPUT = Path("data/sheriff_sales/realauction")
PARSER_VERSION = "realauction_v1"

OH_COUNTIES = [
    "Adams", "Allen", "Ashland", "Ashtabula", "Athens", "Auglaize", "Belmont", "Brown", "Butler", "Carroll",
    "Champaign", "Clark", "Clermont", "Clinton", "Columbiana", "Coshocton", "Crawford", "Cuyahoga", "Darke",
    "Defiance", "Delaware", "Erie", "Fairfield", "Fayette", "Franklin", "Fulton", "Gallia", "Geauga", "Greene",
    "Guernsey", "Hamilton", "Hancock", "Hardin", "Harrison", "Henry", "Highland", "Hocking", "Holmes", "Huron",
    "Jackson", "Jefferson", "Knox", "Lake", "Lawrence", "Licking", "Logan", "Lorain", "Lucas", "Madison",
    "Mahoning", "Marion", "Medina", "Meigs", "Mercer", "Miami", "Monroe", "Montgomery", "Morgan", "Morrow",
    "Muskingum", "Noble", "Ottawa", "Paulding", "Perry", "Pickaway", "Pike", "Portage", "Preble", "Putnam",
    "Richland", "Ross", "Sandusky", "Scioto", "Seneca", "Shelby", "Stark", "Summit", "Trumbull", "Tuscarawas",
    "Union", "Van Wert", "Vinton", "Warren", "Washington", "Wayne", "Williams", "Wood", "Wyandot"]
# Florida counties whose clerk runs foreclosure sales on RealForeclose. Citrus, Hendry,
# Hernando, Lake and Okaloosa answer on the domain but have no foreclosure calendar.
FL_SITES = {
    "Alachua": "alachua", "Bay": "bay", "Brevard": "brevard", "Broward": "broward", "Charlotte": "charlotte",
    "Clay": "clay", "Duval": "duval", "Escambia": "escambia", "Flagler": "flagler",
    "Hillsborough": "hillsborough", "Indian River": "indian-river",
    "Lee": "lee", "Leon": "leon", "Manatee": "manatee", "Marion": "marion", "Martin": "martin",
    "Miami-Dade": "miamidade", "Pasco": "pasco", "Pinellas": "pinellas", "Polk": "polk",
    "Putnam": "putnam", "Santa Rosa": "santarosa", "Sarasota": "sarasota", "St. Lucie": "stlucie",
    "Volusia": "volusia", "Walton": "walton"}

# Colorado Public Trustees on RealForeclose. Hosts differ: Denver uses "www.", the
# others do not. Larimer is collected from CivilView instead; Arapahoe, Jefferson,
# Douglas, Boulder and Pueblo are not on RealAuction.
CO_SITES = {
    "Adams": "https://adams.realforeclose.com", "Denver": "https://www.denver.realforeclose.com",
    "Eagle": "https://eagle.realforeclose.com", "El Paso": "https://elpasoco.realforeclose.com",
    "Mesa": "https://mesa.realforeclose.com", "Summit": "https://summit.realforeclose.com",
    "Weld": "https://weld.realforeclose.com"}

# Texas counties whose tax foreclosure sales run on RealAuction, from the sites'
# own "Jump To" menu. Montgomery and Travis use the realforeclose.com domain.
TX_SITES = {county: f"https://{host}.texas.sheriffsaleauctions.com" for county, host in {
    "Angelina": "angelina", "Aransas": "aransas", "Atascosa": "atascosa", "Caldwell": "caldwell",
    "Cameron": "cameron", "Dallas": "dallas", "El Paso": "elpaso", "Ellis": "ellis", "Galveston": "galveston",
    "Gregg": "gregg", "Hopkins": "hopkins", "Jackson": "jackson", "Kaufman": "kaufman", "Llano": "llano",
    "Matagorda": "matagorda", "Nueces": "nueces", "Orange": "orange", "San Patricio": "sanpatricio",
    "Smith": "smith", "Tyler": "tylercounty", "Victoria": "victoria", "Wilson": "wilson"}.items()}
TX_SITES |= {"Montgomery": "https://montgomery.texas.realforeclose.com",
             "Travis": "https://travis.texas.realforeclose.com"}

SOURCES = {
    "OH": {county: f"https://{county.lower().replace(' ', '')}.sheriffsaleauction.ohio.gov" for county in OH_COUNTIES},
    "FL": {county: f"https://www.{site}.realforeclose.com" for county, site in FL_SITES.items()},
    "CO": CO_SITES,
    "TX": TX_SITES,
}


def snapshot_path(state, county):
    return OUTPUT / f"{state.lower()}_{county.lower().replace(' ', '_').replace('.', '')}.json"


def scrape(state, county, months, from_date=None):
    url = SOURCES[state][county]
    items = RealAuctionAdapter(url, months=months, tax_sales=state == "TX").fetch(today=from_date)
    snapshot = {"state": state, "county": county, "source_url": url, "parser_version": PARSER_VERSION,
                "scraped_at": datetime.now(timezone.utc).isoformat(), "months": months, "items": items}
    path = snapshot_path(state, county)
    path.write_text(json.dumps(snapshot, indent=1) + "\n")
    return len(items)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--state", required=True, choices=sorted(SOURCES))
    parser.add_argument("--counties", nargs="+")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--months", type=int, default=3, help="Calendar months to scan from today")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--from-date", type=date.fromisoformat,
                        help="Include sale days from this date (YYYY-MM-DD) instead of today, to backfill a recent sale")
    args = parser.parse_args()
    counties = sorted(SOURCES[args.state]) if args.all else args.counties or []
    unknown = [county for county in counties if county not in SOURCES[args.state]]
    if unknown:
        parser.error(f"Unknown {args.state} counties: {', '.join(unknown)}")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    failed = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(scrape, args.state, county, args.months, args.from_date): county for county in counties}
        for future in as_completed(futures):
            county = futures[future]
            try:
                print(f"{args.state} {county}: {future.result()} auctions", flush=True)
            except Exception as exc:  # noqa: BLE001 - one county's site must not stop the rest
                # The previous snapshot is kept, so a failed site is never loaded as empty.
                print(f"{args.state} {county}: FAILED, previous snapshot kept ({type(exc).__name__}: {exc})", flush=True)
                failed.append(county)
    if failed:
        raise SystemExit(f"Failed counties: {', '.join(sorted(failed))}")


if __name__ == "__main__":
    main()
