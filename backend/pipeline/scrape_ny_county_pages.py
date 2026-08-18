import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from pipeline.adapters.ny_county_pages import NYCountyPageAdapter
from pipeline.scrape_civilview import json_serializer


SOURCES = {
    "Erie": "https://www4.erie.gov/sheriff/scheduled-sheriffs-sales",
    "Orange": "https://www.orangecountyny.gov/1010/Sheriffs-Sales",
}


async def run(counties: list[str]) -> None:
    output = Path("data/sheriff_sales")
    output.mkdir(parents=True, exist_ok=True)
    for county in counties:
        records = await NYCountyPageAdapter(county, SOURCES[county]).fetch()
        path = output / f"ny_{county.lower()}_sheriff_sales.json"
        path.write_text(json.dumps([asdict(record) for record in records], indent=2,
                                   default=json_serializer) + "\n")
        print(f"{county}: {len(records)} records saved to {path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--counties", nargs="+", choices=sorted(SOURCES))
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(sorted(SOURCES) if args.all else args.counties or []))


if __name__ == "__main__":
    main()
