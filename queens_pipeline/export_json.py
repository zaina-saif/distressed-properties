"""Write one JSON file per active case to data/<county>/export/.

    python export_json.py [--county Queens]

scheduled_auction_date is the earliest event still 'scheduled'. The folder is rewritten
on every run, so a case that went inactive drops out of it.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from db import DATA, connect

STATUS = {"scheduled": "Scheduled", "not_held": "Not Held", "passed": "Passed", "dropped": "Dropped"}


def address(case: sqlite3.Row) -> str | None:
    if not case["property_address"]:
        return None
    place = " ".join(part for part in ("NY", case["zip"]) if part)
    return ", ".join(part for part in (case["property_address"], case["city"], place) if part)


def case_json(connection: sqlite3.Connection, case: sqlite3.Row) -> dict:
    key = (case["county"], case["index_number"])
    events = connection.execute(
        """SELECT auction_date, court, part, event_status FROM auction_events
           WHERE county = ? AND index_number = ? ORDER BY auction_date""", key).fetchall()
    scheduled = [event for event in events if event["event_status"] == "scheduled"]
    latest = events[-1] if events else None
    shown = scheduled[0] if scheduled else latest
    appearances = connection.execute(
        """SELECT appearance_date, purpose, outcome, justice, part FROM appearances
           WHERE county = ? AND index_number = ? ORDER BY appearance_date DESC""", key).fetchall()
    return {
        "county": case["county"],
        "index_number": case["index_number"],
        "court": shown["court"] if shown else None,
        "court_part": shown["part"] if shown else None,
        "scheduled_auction_date": scheduled[0]["auction_date"] if scheduled else None,
        "status": "Scheduled" if scheduled else STATUS.get(latest["event_status"]) if latest else None,
        "plaintiff": case["plaintiff"],
        "defendant": case["defendant"],
        "property_details": {
            "address": address(case),
            "borough_block_lot": case["borough_block_lot"],
            "unpaid_principal_balance": case["unpaid_principal"],
            "approximate_judgment": case["approximate_judgment"],
            "approximate_lien_amount": case["approximate_lien_amount"],
        },
        "referee_name": case["referee_name"],
        "plaintiff_attorney": case["plaintiff_attorney"],
        "times_scheduled": case["times_scheduled"],
        "appearance_history": [dict(row) for row in appearances],
        "efiled_documents_summary": {
            "initiating_doc": case["initiating_doc"],
            "filing_date": case["filing_date"],
        },
    }


def export(connection: sqlite3.Connection, county: str, folder: Path) -> int:
    folder.mkdir(parents=True, exist_ok=True)
    for stale in folder.glob("*.json"):
        stale.unlink()
    cases = connection.execute("SELECT * FROM cases WHERE county = ? AND lifecycle = 'active' ORDER BY index_number",
                               (county,)).fetchall()
    for case in cases:
        path = folder / f"{case['index_number'].replace('/', '-')}.json"
        path.write_text(json.dumps(case_json(connection, case), indent=2) + "\n")
    return len(cases)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--county", default="Queens")
    args = parser.parse_args()
    folder = DATA / args.county.lower().replace(" ", "_") / "export"
    count = export(connect(), args.county, folder)
    print(f"Wrote {count} case files to {folder}")


if __name__ == "__main__":
    main()
