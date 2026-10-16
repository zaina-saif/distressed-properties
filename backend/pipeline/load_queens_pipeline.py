"""Load the local NY court pipeline (queens_pipeline/: Queens, New York County, ...) into the live listings.

queens_pipeline/ reads the WebCivil auction calendar and the case files the operator
saved by hand into its own SQLite database. This puts every active case that has an
address on the site as a referee auction, under the same source and key (index number)
as pipeline.load_ny_court_pdfs, so a case loaded by either one is updated, not duplicated.

    python -m pipeline.load_queens_pipeline --dry-run
    python -m pipeline.load_queens_pipeline
    python -m pipeline.load_queens_pipeline --county "New York"

Each calendar date becomes a status-history row: "Not Held" as adjourned, a date still
on the calendar as scheduled, one that went by or left the calendar as
sold_or_cancelled_unverified. The case's WebCivil appearance history adds its earlier
auction dates and outcomes (load_ny_court_pdfs.apply_appearances). Cases without an
address (no Notice of Sale or summons saved yet) cannot be listed and are counted.

Each listed case also gets a case summary (ny_court_case_summaries, migration 043): what
the summons and complaint, the Notice of Sale, the appearances and the auction calendar
say, with the case's stages in order. The dashboard shows it in place of a sale page.
Defendants' names are left out, as everywhere else.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter
from datetime import date
from pathlib import Path

from sqlalchemy import text

from app.database.session import engine
from pipeline.load_ny_court_pdfs import SOURCE_SYSTEM, WEBCIVIL_URL, apply_appearances, bbl
from pipeline.ny_case_summary import build_summary
from pipeline.sale_listing_loader import Sale, load_sales

DB_PATH = Path(__file__).resolve().parents[2] / "queens_pipeline" / "data" / "sheriffsale.db"
PARSER_VERSION = "queens_pipeline_v1"
# ZIPs printed wrongly in the source, corrected by hand and keyed by (county, index number).
ZIP_CORRECTIONS = {
    ("Queens", "710760/2021"): "11417",  # the notice prints 11471; 83-02 133rd Avenue, Ozone Park is 11417
}
# Addresses the filings print wrongly or not at all, checked against the lot's address in NYC PLUTO
# (64uk-42ks) where it has one (condominium units have none): (street, city, ZIP).
ADDRESS_CORRECTIONS = {
    ("Queens", "703782/2019"): ("41-47 70th Street", "Woodside", "11377"),  # the notice names only Block 1310 Lot 9
    ("Queens", "708268/2023"): ("13-61 Dickens Street", "Far Rockaway", "11691"),  # printed "1361 Dickens St"
    ("Queens", "711182/2017"): ("23-64 Mott Avenue", "Far Rockaway", "11691"),  # printed "2364 Motts Ave."
    ("Queens", "700059/2022"): ("33-36 Bay Court", "Far Rockaway", "11691"),  # printed "3336 Baycourt Avenue"
    ("Queens", "720461/2023"): ("14-07 Cross Bay Boulevard", "Broad Channel", "11693"),  # printed "1407 Cross Bay Boulevard"
    # "300 WEST14THSTREET,UNIT304A/K/A 77 EIGHTHAVENUE, NEW NY YORK, 10014" in the OCR'd notice.
    ("New York", "159971/2014"): ("300 West 14th Street, Unit 304", "New York", "10014"),
    # The notice describes the two units; the complaint names the building.
    ("New York", "850089/2023"): ("525 East 80th Street, Units 7B and 7C", "New York", "10075"),
    ("New York", "850221/2025"): ("435 East 117th Street, Apt 3", "New York", "10035"),  # no notice yet; the complaint
    ("New York", "850279/2021"): ("1696 Lexington Avenue", "New York", "10029"),  # PLUTO lists the lot as 1694
    ("New York", "850304/2024"): ("123 Baxter Street, Unit Garage", "New York", "10013"),  # the notice gives no ZIP
    # The notice's text layer is unreadable; the complaint and the notice's description name 41 West 36th Street
    # (Block 838 Lot 20 in PLUTO).
    ("New York", "850385/2024"): ("41 West 36th Street", "New York", "10018"),
    ("New York", "850475/2023"): ("20 West Street, Unit 22J", "New York", "10004"),  # printed "Unit 22 J"
}
# Block and lot the filings leave out, from PLUTO: (county, index number) -> "borough-block-lot".
BLOCK_LOT_CORRECTIONS = {
    ("New York", "850385/2024"): "1-838-20",
}
# Cases not listed, with the reason.
EXCLUDED = {
    # One sale of three parcels (Ridgewood, Jamaica and 2415 Dean Street, Brooklyn) for one lien amount:
    # a single listing could show neither the right address nor a meaningful equity figure.
    ("Queens", "710387/2023"): "three parcels in Queens and Brooklyn sold together",
    # Timeshare foreclosures: a fraction of a percent of a hotel unit, used a week or so a year. The
    # building's value (Zillow, NYC DOF) says nothing about the interest's, so equity would be wrong.
    ("New York", "850062/2024"): "timeshare interest at 102 West 57th Street",
    ("New York", "850341/2023"): "timeshare interest at 102 West 57th Street",
    ("New York", "850292/2023"): "timeshare interest at 1335 Avenue of the Americas",
}
EVENT_STATUS = {
    "scheduled": ("scheduled", "Referee auction on the court calendar"),
    "not_held": ("adjourned", "Not Held (court calendar)"),
    "passed": ("sold_or_cancelled_unverified", "Auction date passed; result not published"),
    "dropped": ("sold_or_cancelled_unverified", "Taken off the court calendar before the auction date"),
}


def read_cases(connection: sqlite3.Connection, county: str) -> list[dict]:
    cases = []
    for case in connection.execute("SELECT * FROM cases WHERE county = ? AND lifecycle = 'active' ORDER BY index_number",
                                   (county,)):
        key = (county, case["index_number"])
        if key in EXCLUDED:
            continue
        case = dict(case)
        if fixed := ADDRESS_CORRECTIONS.get(key):
            case["property_address"], case["city"], case["zip"] = fixed
        case["zip"] = ZIP_CORRECTIONS.get(key, case["zip"])
        case["borough_block_lot"] = BLOCK_LOT_CORRECTIONS.get(key, case["borough_block_lot"])
        events = connection.execute("""SELECT * FROM auction_events
            WHERE county = ? AND index_number = ? ORDER BY auction_date""", key).fetchall()
        appearances = connection.execute("""SELECT appearance_date, part, justice, purpose, outcome FROM appearances
            WHERE county = ? AND index_number = ? ORDER BY appearance_date""", key).fetchall()
        sections = {section for (names,) in connection.execute(
            "SELECT sections FROM case_files WHERE county = ? AND index_number = ?", key) for section in names.split(",")}
        cases.append({**case, "events": [dict(event) for event in events], "sections": sorted(sections),
                      "appearances": [dict(row) for row in appearances],
                      "auctions": [{"date": row["appearance_date"], "outcome": row["outcome"]}
                                   for row in appearances if (row["purpose"] or "").startswith("Auction")]})
    return cases


def block_and_lots(case: dict) -> tuple[str | None, list[str]]:
    """'4-12073-429/430' -> ('12073', ['429', '430'])."""
    if not case["borough_block_lot"]:
        return None, []
    _, block, lots = case["borough_block_lot"].split("-")
    return block, lots.split("/")


def details(case: dict, sale_date: str | None) -> str:
    parts = ["Court-ordered referee foreclosure auction."]
    if sale_date:
        event = next((event for event in case["events"] if event["auction_date"] == sale_date), {})
        summary_event = next((e for e in build_summary(case, [], date.today())["auction_calendar"]
                              if e["date"] == sale_date), {})
        when = " ".join(filter(None, [sale_date, summary_event.get("time") and f"at {summary_event['time']}"]))
        place = summary_event.get("location") or "Foreclosure Auction Part"
        parts.append(f"Auction: {when}, {case['county']} County Supreme Court, {place}.")
        if event.get("event_status") == "not_held" and summary_event.get("remarks"):
            parts.append(f"Court calendar: {summary_event['remarks']}.")
    if case["referee_name"]:
        parts.append(f"Referee: {case['referee_name']}.")
    if case["approximate_judgment"]:
        parts.append(f"Approximate judgment: ${case['approximate_judgment']:,.2f} plus interest and costs (the minimum "
                     "bid is set by the plaintiff at the sale; the judgment is an estimate of it).")
    if case["approximate_lien_amount"]:
        parts.append(f"Notice states an approximate lien amount of ${case['approximate_lien_amount']:,.2f} plus "
                     "interest and costs, used as the minimum-bid estimate (the plaintiff sets the opening bid at the sale).")
    if case["unpaid_principal"]:
        parts.append(f"Unpaid principal stated in the complaint: ${case['unpaid_principal']:,.2f} "
                     "(when the case was filed; not the judgment).")
    block, lots = block_and_lots(case)
    if block:
        parts.append(f"Block {block}, Lot{'s' if len(lots) > 1 else ''} {' and '.join(lots)}.")
    if case["plaintiff_attorney"]:
        parts.append(f"Plaintiff's attorney: {case['plaintiff_attorney']}.")
    parts.append(f"Index No. {case['index_number']} (look up filings on NYSCEF). Winning bidders typically "
                 "pay a 10% deposit at the auction.")
    return " ".join(parts)


def to_sales(case: dict) -> list[Sale]:
    """One Sale per calendar date, oldest first, so the listing ends on its latest date."""
    block, lots = block_and_lots(case)
    common = dict(
        case=case["index_number"], street=case["property_address"], city=case["city"],
        zip_code=case["zip"],
        raw={**{k: v for k, v in case.items()
                if k not in ("defendant", "defendant_attorney", "caption", "appearances", "sections")},
             "parser_version": PARSER_VERSION},
        parcel=f"Block {block} Lot{'s' if len(lots) > 1 else ''} {' and '.join(lots)}" if block else None,
        # The calendar cuts long plaintiff names short, so apply_details fills it only where it is missing.
        judgment=case["approximate_judgment"], plaintiff=None,
        attorney=case["plaintiff_attorney"], property_number=bbl(case["county"], block, lots[0] if lots else None))
    sales = []
    for event in case["events"]:
        status, raw_status = EVENT_STATUS[event["event_status"]]
        if event.get("remarks") and event["event_status"] == "not_held":
            # "CANCELED VIA EMAIL 9/18/26, SUB REF NEEDED": the clerk's reason, after the courtroom.
            reason = re.sub(r"^\d+ CENTRE STREET ROOM \d+\s*", "", event["remarks"], flags=re.I).strip()
            raw_status = f"{raw_status}: {reason}" if reason else raw_status
        sales.append(Sale(**common, sale_date=date.fromisoformat(event["auction_date"]), status=status,
                          raw_status=raw_status))
    return sales


def apply_details(cases: list[dict]) -> Counter:
    counts = Counter()
    with engine.begin() as connection:
        for case in cases:
            row = connection.execute(text("""SELECT id, current_sale_date::date, judgment_amount FROM sheriff_sales
                WHERE state='NY' AND county=:county AND source_system=:source AND sheriff_number=:index"""),
                {"county": case["county"], "source": SOURCE_SYSTEM, "index": case["index_number"]}).first()
            if not row:
                continue
            sale_id, sale_date, judgment = row
            # Keeps a WebCivil calendar note added by apply_appearances.
            connection.execute(text("""UPDATE sheriff_sales SET description_text=:details
                || COALESCE(' ' || substring(description_text from ' (Court calendar \\(WebCivil\\):.*)$'), ''),
                plaintiff=COALESCE(plaintiff, :plaintiff), notice_lien_amount=COALESCE(:lien, notice_lien_amount),
                updated_at=NOW() WHERE id=:id"""),
                {"details": details(case, sale_date.isoformat() if sale_date else None), "id": sale_id,
                 "lien": case["approximate_lien_amount"],
                 "plaintiff": (case["plaintiff"] or "").rstrip(" ,") or None})
            counts["details"] += 1
            connection.execute(text("""INSERT INTO ny_court_case_summaries (sheriff_sale_id, county, index_number, summary)
                VALUES (:id, :county, :index, CAST(:summary AS JSONB))
                ON CONFLICT (sheriff_sale_id) DO UPDATE SET summary = EXCLUDED.summary, updated_at = NOW()"""),
                {"id": sale_id, "county": case["county"], "index": case["index_number"],
                 "summary": json.dumps(build_summary(case, case["sections"], date.today()))})
            counts["summaries"] += 1
            # A notice that states only a lien amount has no judgment: an earlier load that
            # stored the lien amount as the judgment is cleared.
            lien = case["approximate_lien_amount"]
            if lien and not case["approximate_judgment"] and judgment is not None and float(judgment) == lien:
                connection.execute(text("UPDATE sheriff_sales SET judgment_amount=NULL WHERE id=:id"), {"id": sale_id})
                counts["lien_amount_removed_from_judgment"] += 1
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, default=DB_PATH, help="the queens_pipeline SQLite database")
    parser.add_argument("--county", default="Queens")
    parser.add_argument("--dry-run", action="store_true", help="report what would load; write nothing")
    args = parser.parse_args()
    connection = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    cases = read_cases(connection, args.county)
    listed = [case for case in cases if case["property_address"] and case["city"] and case["events"]]
    sales = [sale for case in listed for sale in to_sales(case)]
    summary = {
        "active_cases": len(cases), "with_address": len(listed), "without_address": len(cases) - len(listed),
        "calendar_dates": len(sales), "with_judgment": sum(1 for c in listed if c["approximate_judgment"]),
        "with_block_lot": sum(1 for c in listed if c["borough_block_lot"]),
        "with_auction_history": sum(1 for c in listed if c["auctions"]),
    }
    print(json.dumps(summary, indent=1))
    if args.dry_run:
        for case in listed:
            print(json.dumps({"index": case["index_number"], "address": f"{case['property_address']}, {case['city']} "
                              f"{case['zip']}",
                              "dates": [(s.sale_date.isoformat(), s.status) for s in to_sales(case)],
                              "judgment": case["approximate_judgment"], "bbl": to_sales(case)[0].property_number}))
        return
    sales.sort(key=lambda sale: sale.sale_date)
    result = load_sales("NY", args.county, SOURCE_SYSTEM, WEBCIVIL_URL, sales,
                        job=f"queens_pipeline_{args.county.lower().replace(' ', '_')}", complete=False)
    print(f"NY {args.county}: {result}")
    print(f"Notice details: {dict(apply_details(listed))}")
    histories = [{"county": case["county"], "index_number": case["index_number"], "auctions": case["auctions"]}
                 for case in listed if case["auctions"]]
    print(f"WebCivil auction histories: {apply_appearances(histories, date.today())}")


if __name__ == "__main__":
    main()
