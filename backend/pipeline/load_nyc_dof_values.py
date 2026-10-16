"""NYC Department of Finance market values for open NYC listings Zillow has no Zestimate for.

    python -m pipeline.load_nyc_dof_values --dry-run
    python -m pipeline.load_nyc_dof_values
    python -m pipeline.load_nyc_dof_values --counties Queens

Each tax lot's market value comes from NYC Open Data's "Property Valuation and
Assessment Data" (8y4t-faws): the latest fiscal year's most recent roll (final over
tentative), curmkttot. A listing on several lots ("Block 809 Lots 42 and 43") gets
their sum. The value is stored in property_valuations as provider
'nyc_dof_market_value', with the lots, year and building class in provider_response;
the API uses it for the market value and equity only while there is no Zestimate.
DOF market values are the city's assessment estimates, not appraisals, and often
differ from sale prices.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import date

import httpx
from sqlalchemy import text

from app.api.properties import NYC_DOF_PROVIDER
from app.database.session import engine

DATASET = "https://data.cityofnewyork.us/resource/8y4t-faws.json"
SOURCE_PAGE = "https://data.cityofnewyork.us/City-Government/Property-Valuation-and-Assessment-Data-Tax-Classes/8y4t-faws"
BOROUGH = {"New York": "1", "Bronx": "2", "Kings": "3", "Queens": "4", "Richmond": "5"}


def listings(counties: list[str] | None = None) -> list[dict]:
    """Open NYC listings with a BBL and no Zestimate."""
    with engine.connect() as connection:
        return [dict(row) for row in connection.execute(text("""
            SELECT DISTINCT ON (p.id) p.id::text AS property_id, p.street_address, ss.county,
                   ss.property_number, ss.map_number
            FROM sheriff_sales ss JOIN properties p ON p.id = ss.property_id
            WHERE ss.state = 'NY' AND ss.county = ANY(:counties)
              AND ss.current_status IN ('scheduled', 'adjourned', 'scheduled_unverified')
              AND p.valuation_excluded_reason IS NULL
              AND ss.property_number ~ '^[1-5]-[0-9]{5}-[0-9]{4}$'
              AND NOT EXISTS (SELECT 1 FROM apify_zillow_results z WHERE z.property_id = p.id AND z.is_current
                              AND z.zestimate IS NOT NULL AND z.match_status <> 'invalid')
            ORDER BY p.id"""), {"counties": counties or list(BOROUGH)}).mappings()]


def lots(listing: dict) -> tuple[str, str, list[str]]:
    """(borough, block, lots): the BBL's lot plus any others the parcel text names."""
    borough, block, lot = listing["property_number"].split("-")
    named = re.findall(r"\d+", (listing["map_number"] or "").split("Lot", 1)[-1]) if "Lot" in (listing["map_number"] or "") else []
    return borough, str(int(block)), sorted({str(int(lot)), *(str(int(n)) for n in named)}, key=int)


def market_value(client: httpx.Client, borough: str, block: str, lot: str) -> dict | None:
    for attempt in range(5):
        response = client.get(DATASET, params={
            "boro": borough, "block": block, "lot": lot, "$order": "year DESC, period DESC", "$limit": "1",
            "$select": "parid,year,period,curmkttot,curtaxclass,bldg_class"})
        if response.status_code == 429 or response.status_code >= 500:
            time.sleep(2 * (attempt + 1))
            continue
        response.raise_for_status()
        rows = response.json()
        return rows[0] if rows and float(rows[0].get("curmkttot") or 0) > 0 else None
    raise RuntimeError(f"NYC Open Data kept refusing {borough}-{block}-{lot}")


def fill(counties: list[str] | None = None, dry_run: bool = False) -> dict[str, int]:
    """Look up and store the values; per-listing lines go to stdout (the refresh sends them to its log).
    A listing whose current DOF value is unchanged (same lots and value) is not written again."""
    found, unchanged = [], 0
    with httpx.Client(timeout=30, headers={"User-Agent": "SheriffSaleHunter valuation lookup"}) as client:
        rows = listings(counties)
        for listing in rows:
            borough, block, lot_numbers = lots(listing)
            values = [market_value(client, borough, block, lot) for lot in lot_numbers]
            if not all(values):
                print(f"  {listing['street_address']}: no DOF market value for every lot", flush=True)
                continue
            total = sum(float(value["curmkttot"]) for value in values)
            found.append((listing, total, values))
            print(f"  {listing['street_address']}: ${total:,.0f} ({len(values)} lot{'s' if len(values) > 1 else ''}, "
                  f"FY{values[0]['year']}, class {values[0]['bldg_class']})", flush=True)
    saved = 0
    if not dry_run:
        with engine.begin() as connection:
            for listing, total, values in found:
                parids = ",".join(value["parid"] for value in values)
                current = connection.execute(text("""SELECT estimated_value, provider_property_id FROM property_valuations
                    WHERE property_id = CAST(:id AS uuid) AND provider = :provider AND is_current"""),
                    {"id": listing["property_id"], "provider": NYC_DOF_PROVIDER}).first()
                if current and float(current[0]) == total and current[1] == parids:
                    unchanged += 1
                    continue
                connection.execute(text("""UPDATE property_valuations SET is_current = FALSE
                    WHERE property_id = CAST(:id AS uuid) AND provider = :provider AND is_current"""),
                    {"id": listing["property_id"], "provider": NYC_DOF_PROVIDER})
                connection.execute(text("""INSERT INTO property_valuations (property_id, provider, estimated_value,
                    provider_property_id, provider_response, effective_date, is_current)
                    VALUES (CAST(:id AS uuid), :provider, :value, :parids, CAST(:response AS JSONB), :effective, TRUE)"""), {
                        "id": listing["property_id"], "provider": NYC_DOF_PROVIDER, "value": total, "parids": parids,
                        "response": json.dumps({"source": SOURCE_PAGE, "method": "NYC DOF market value (curmkttot), "
                                                "summed over the listing's tax lots", "lots": values}),
                        # The fiscal year's values are as of the January 5 taxable status date before it.
                        "effective": date(int(values[0]["year"]) - 1, 1, 5)})
                saved += 1
    return {"without_zestimate": len(rows), "valued": len(found), "saved": saved, "unchanged": unchanged}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--counties", nargs="+", choices=sorted(BOROUGH), help="NYC counties (default: all five)")
    args = parser.parse_args()
    print(json.dumps(fill(args.counties, args.dry_run)))


if __name__ == "__main__":
    main()
