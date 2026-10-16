"""A NY referee foreclosure case in one view, for the dashboard (app/api/court_cases.py).

Built by pipeline.load_queens_pipeline from what queens_pipeline/ read out of the
case's files: the summons and complaint (filing, original lender, unpaid principal),
the Notice of Sale (referee, judgment or lien amount, judgment date), the WebCivil
appearance history (conferences, motions, auctions) and the auction calendar (dates,
times, the clerk's remarks). `stages` retells how the case moved, oldest first.
Defendants' names are never included.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

SECTION_TITLES = {
    "summons_complaint": "Summons and complaint",
    "notice_of_sale": "Notice of Sale",
    "judgment_of_foreclosure": "Judgment of foreclosure and sale",
    "notice_of_pendency": "Notice of pendency",
    "appearances": "WebCivil appearances",
    "case_detail": "WebCivil case detail",
}
# The courtroom a calendar's remarks start with ("60 CENTRE STREET ROOM 130 CANCELED VIA EMAIL ...").
ROOM = re.compile(r"^(\d+[\w-]* [A-Z0-9 .]+? (?:ROOM|COURTROOM|PART) #?\s*\w+)\s*", re.I)


def _kind(purpose: str | None) -> str:
    head = (purpose or "").split("-", 1)[0].strip().lower()
    return {"conference": "conference", "motion": "motion", "auction": "auction", "trial": "trial",
            "hearing": "hearing", "conversion": "conference"}.get(head, "other")


def _room_and_remarks(remarks: str | None) -> tuple[str | None, str | None]:
    if not remarks:
        return None, None
    if match := ROOM.match(remarks):
        rest = remarks[match.end():].strip()
        return match[1].title(), rest or None
    return None, remarks


def _time(value: str | None) -> str | None:
    """'14:15' -> '2:15 PM'."""
    if not value or not re.fullmatch(r"\d{1,2}:\d{2}", value):
        return value or None
    hour, minute = map(int, value.split(":"))
    return f"{(hour % 12) or 12}:{minute:02d} {'AM' if hour < 12 else 'PM'}"


def _span(rows: list[dict]) -> str:
    first, last = rows[0]["date"], rows[-1]["date"]
    return first if first == last else f"{first} to {last}"


def build_summary(case: dict, sections: list[str], today: date) -> dict[str, Any]:
    appearances = [{"date": row["appearance_date"], "part": row["part"], "justice": row["justice"],
                    "purpose": row["purpose"], "outcome": row["outcome"] or None, "kind": _kind(row["purpose"])}
                   for row in case.get("appearances", []) if row.get("appearance_date")]
    calendar = []
    for event in case.get("events", []):
        room, remarks = _room_and_remarks(event.get("remarks"))
        calendar.append({"date": event["auction_date"], "time": _time(event.get("time")), "location": room,
                         "outcome": event.get("outcome"), "status": event["event_status"], "remarks": remarks})
    upcoming = [event for event in calendar if event["status"] == "scheduled" and event["date"] >= today.isoformat()]
    stages: list[dict[str, Any]] = []
    if case.get("filing_date"):
        detail = case.get("initiating_doc") or "Foreclosure filed"
        if case.get("original_mortgagee"):
            detail += f"; original lender {case['original_mortgagee']}"
        if case.get("unpaid_principal"):
            detail += f"; unpaid principal ${case['unpaid_principal']:,.2f}"
        stages.append({"stage": "Case filed", "date": case["filing_date"], "detail": detail})
    for kind, label in (("conference", "Settlement and status conferences"), ("motion", "Motions")):
        rows = [row for row in appearances if row["kind"] == kind]
        if rows:
            outcome = next((row["outcome"] for row in reversed(rows) if row["outcome"]), None)
            stages.append({"stage": label, "date": rows[0]["date"],
                           "detail": f"{len(rows)} court date{'s' if len(rows) > 1 else ''}, {_span(rows)}"
                                     + (f"; last outcome: {outcome}" if outcome else "")})
    if case.get("judgment_date"):
        amount = (f"approximate judgment ${case['approximate_judgment']:,.2f}" if case.get("approximate_judgment")
                  else f"approximate lien amount ${case['approximate_lien_amount']:,.2f}"
                  if case.get("approximate_lien_amount") else None)
        stages.append({"stage": "Judgment of foreclosure and sale", "date": case["judgment_date"],
                       "detail": "Entered" + (f"; {amount}" if amount else "")
                                 + (f"; referee {case['referee_name']}" if case.get("referee_name") else "")})
    # Past auction dates: the appearance history, plus calendar dates it does not have yet.
    held = {row["date"]: row["outcome"] for row in appearances if row["kind"] == "auction" and row["date"] < today.isoformat()}
    for event in calendar:
        if event["date"] < today.isoformat():
            held.setdefault(event["date"], event["outcome"])
    if held:
        dates = sorted(held)
        not_held = sum(1 for outcome in held.values() if outcome == "Not Held")
        sold = [day for day in dates if held[day] == "Sold"]
        detail = f"{len(dates)} auction date{'s' if len(dates) > 1 else ''} so far, {dates[0]} to {dates[-1]}"
        if not_held:
            detail += f"; {not_held} not held"
        if sold:
            detail += f"; recorded as sold on {', '.join(sold)} (a later date means that sale did not close)"
        stages.append({"stage": "Auctions scheduled", "date": dates[0], "detail": detail})
    cancelled = [event for event in calendar if event["status"] == "not_held" and event["date"] >= today.isoformat()]
    for event in cancelled:
        stages.append({"stage": "Auction taken off the calendar", "date": event["date"],
                       "detail": event["remarks"] or "Not Held"})
    if upcoming:
        nxt = upcoming[0]
        stages.append({"stage": "Next auction", "date": nxt["date"],
                       "detail": ", ".join(filter(None, [nxt["time"], nxt["location"]])) or "On the court calendar"})
    stages.sort(key=lambda stage: stage["date"])
    block_lot = case.get("borough_block_lot")
    return {
        "county": case["county"],
        "index_number": case["index_number"],
        "court": f"{case['county']} County Supreme Court",
        "address": ", ".join(filter(None, [case.get("property_address"), case.get("city")])) +
                   (f" {case['zip']}" if case.get("zip") else ""),
        "block_lot": block_lot,
        "plaintiff": (case.get("plaintiff") or "").rstrip(" ,") or None,
        "plaintiff_attorney": case.get("plaintiff_attorney"),
        "referee": case.get("referee_name"),
        "justice": case.get("justice"),
        "filing_date": case.get("filing_date"),
        "initiating_document": case.get("initiating_doc"),
        "original_lender": case.get("original_mortgagee"),
        "unpaid_principal": case.get("unpaid_principal"),
        "approximate_judgment": case.get("approximate_judgment"),
        "approximate_lien_amount": case.get("approximate_lien_amount"),
        "judgment_date": case.get("judgment_date"),
        "next_auction": upcoming[0] if upcoming else None,
        "years_in_foreclosure": round((today - date.fromisoformat(case["filing_date"])).days / 365.25, 1)
        if case.get("filing_date") else None,
        "stages": stages,
        "auction_calendar": calendar,
        "appearances": sorted(appearances, key=lambda row: row["date"], reverse=True),
        "sources": [SECTION_TITLES[section] for section in SECTION_TITLES if section in sections]
                   + (["WebCivil auction calendar"] if calendar else []),
        "built_on": today.isoformat(),
    }
