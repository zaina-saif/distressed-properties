"""Load the local Queens court pipeline (queens_pipeline/) into the live listings.

queens_pipeline/ reads the WebCivil auction calendar and the case files the operator
saved by hand into its own SQLite database. This puts every active case that has an
address on the site as a referee auction, under the same source and key (index number)
as pipeline.load_ny_court_pdfs, so a case loaded by either one is updated, not duplicated.

    python -m pipeline.load_queens_pipeline --dry-run
    python -m pipeline.load_queens_pipeline

Each calendar date becomes a status-history row: "Not Held" as adjourned, a date still
on the calendar as scheduled, one that went by or left the calendar as
sold_or_cancelled_unverified. The case's WebCivil appearance history adds its earlier
auction dates and outcomes (load_ny_court_pdfs.apply_appearances). Cases without an
address (no Notice of Sale or summons saved yet) cannot be listed and are counted.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from datetime import date
from pathlib import Path

from sqlalchemy import text

from app.database.session import engine
from pipeline.load_ny_court_pdfs import SOURCE_SYSTEM, WEBCIVIL_URL, apply_appearances, bbl
from pipeline.sale_listing_loader import Sale, load_sales

DB_PATH = Path(__file__).resolve().parents[2] / "queens_pipeline" / "data" / "sheriffsale.db"
PARSER_VERSION = "queens_pipeline_v1"
# ZIPs printed wrongly in the source, corrected by hand and keyed by index number.
ZIP_CORRECTIONS = {
    "710760/2021": "11417",  # the notice prints 11471; 83-02 133rd Avenue, Ozone Park is 11417
}
# Addresses the filings print wrongly or not at all, checked against the lot's address in NYC PLUTO
# (64uk-42ks) and keyed by index number: (street, city, ZIP).
ADDRESS_CORRECTIONS = {
    "703782/2019": ("41-47 70th Street", "Woodside", "11377"),  # the notice names only Block 1310 Lot 9
    "708268/2023": ("13-61 Dickens Street", "Far Rockaway", "11691"),  # printed "1361 Dickens St"
    "711182/2017": ("23-64 Mott Avenue", "Far Rockaway", "11691"),  # printed "2364 Motts Ave."
    "700059/2022": ("33-36 Bay Court", "Far Rockaway", "11691"),  # printed "3336 Baycourt Avenue"
    "720461/2023": ("14-07 Cross Bay Boulevard", "Broad Channel", "11693"),  # printed "1407 Cross Bay Boulevard"
}
# Cases not listed, with the reason.
EXCLUDED = {
    # One sale of three parcels (Ridgewood, Jamaica and 2415 Dean Street, Brooklyn) for one lien amount:
    # a single listing could show neither the right address nor a meaningful equity figure.
    "710387/2023": "three parcels in Queens and Brooklyn sold together",
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
        if case["index_number"] in EXCLUDED:
            continue
        case = dict(case)
        if fixed := ADDRESS_CORRECTIONS.get(case["index_number"]):
            case["property_address"], case["city"], case["zip"] = fixed
        key = (county, case["index_number"])
        events = connection.execute("""SELECT auction_date, part, outcome, event_status FROM auction_events
            WHERE county = ? AND index_number = ? ORDER BY auction_date""", key).fetchall()
        auctions = connection.execute("""SELECT appearance_date, outcome FROM appearances WHERE county = ?
            AND index_number = ? AND purpose LIKE 'Auction%' ORDER BY appearance_date""", key).fetchall()
        cases.append({**case, "events": [dict(event) for event in events],
                      "auctions": [{"date": row["appearance_date"], "outcome": row["outcome"]} for row in auctions]})
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
        parts.append(f"Auction: {sale_date}, {case['county']} County Supreme Court, Foreclosure Auction Part.")
    if case["referee_name"]:
        parts.append(f"Referee: {case['referee_name']}.")
    if case["approximate_judgment"]:
        parts.append(f"Approximate judgment: ${case['approximate_judgment']:,.2f} plus interest and costs (the minimum "
                     "bid is set by the plaintiff at the sale; the judgment is an estimate of it).")
    if case["approximate_lien_amount"]:
        parts.append(f"Notice states an approximate lien amount of ${case['approximate_lien_amount']:,.2f} plus "
                     "interest and costs; this is not treated as a verified judgment or unpaid principal balance.")
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
        zip_code=ZIP_CORRECTIONS.get(case["index_number"], case["zip"]),
        raw={**{k: v for k, v in case.items() if k != "defendant"}, "parser_version": PARSER_VERSION},
        parcel=f"Block {block} Lot{'s' if len(lots) > 1 else ''} {' and '.join(lots)}" if block else None,
        # The calendar cuts long plaintiff names short, so apply_details fills it only where it is missing.
        judgment=case["approximate_judgment"], plaintiff=None,
        attorney=case["plaintiff_attorney"], property_number=bbl(case["county"], block, lots[0] if lots else None))
    sales = []
    for event in case["events"]:
        status, raw_status = EVENT_STATUS[event["event_status"]]
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
                plaintiff=COALESCE(plaintiff, :plaintiff), updated_at=NOW() WHERE id=:id"""),
                {"details": details(case, sale_date.isoformat() if sale_date else None), "id": sale_id,
                 "plaintiff": (case["plaintiff"] or "").rstrip(" ,") or None})
            counts["details"] += 1
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
                              f"{ZIP_CORRECTIONS.get(case['index_number'], case['zip'])}",
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
