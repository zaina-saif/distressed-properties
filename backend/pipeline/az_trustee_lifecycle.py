"""Link Arizona trustee-sale recordings into foreclosures and give each one a status.

A foreclosure is keyed by the deed of trust it enforces (`dot:<recording number>`), or by
its notice when the deed of trust's number could not be read (`ns:<recording number>`).
Its notices, in recording order, give the sale dates: a later notice for the same deed
of trust re-sets the sale, and the dates of the earlier ones become postponements.

A cancellation or trustee's deed upon sale is tied to a foreclosure by, in order:
  1. the notice's recording number cited in it,
  2. the deed of trust's recording number cited in it,
  3. the same trustee's sale (TS) number,
  4. the same APN, for a notice recorded before it.
Matching by trustor name, which the task also suggests, is not done: names are not kept.
An event recorded before every notice it matches is left unlinked.

Status, in the task's terms (`lifecycle`): noticed, postponed (a later notice moved the
sale), cancelled, sold. The status checker (pipeline.az_sale_status) can also postpone.
"""
import re
from dataclasses import dataclass, field


def ts_key(value: str | None) -> str | None:
    key = re.sub(r"[^A-Z0-9]", "", (value or "").upper())
    return key if len(key) >= 5 and re.search(r"\d", key) else None


@dataclass
class Foreclosure:
    key: str
    notices: list[dict] = field(default_factory=list)
    cancellation: dict | None = None
    deed: dict | None = None
    links: list[str] = field(default_factory=list)

    @property
    def notice(self) -> dict:
        return self.notices[-1]

    @property
    def lifecycle(self) -> str:
        if self.deed:
            return "sold"
        if self.cancellation:
            return "cancelled"
        return "postponed" if len({n.get("sale_date") for n in self.notices if n.get("sale_date")}) > 1 else "noticed"

    @property
    def earlier_sale_dates(self) -> list[str]:
        dates = [n["sale_date"] for n in self.notices[:-1] if n.get("sale_date")]
        return [day for index, day in enumerate(dates) if day not in dates[:index] and day != self.notice.get("sale_date")]


def group_notices(notices: list[dict]) -> dict[str, Foreclosure]:
    foreclosures: dict[str, Foreclosure] = {}
    for notice in sorted(notices, key=lambda n: (n["recording_date"], n["recording_number"])):
        key = f"dot:{notice['deed_of_trust']}" if notice.get("deed_of_trust") else f"ns:{notice['recording_number']}"
        foreclosures.setdefault(key, Foreclosure(key)).notices.append(notice)
    return foreclosures


def match(event: dict, foreclosures: dict[str, Foreclosure]) -> tuple[Foreclosure | None, str | None]:
    """The foreclosure an event belongs to and how it was matched."""
    references = set(event.get("references") or [])
    candidates = [f for f in foreclosures.values() if f.notices[0]["recording_date"] <= event["recording_date"]]
    for how, test in (
            ("notice_reference", lambda f: references & {n["recording_number"] for n in f.notices}),
            ("deed_of_trust", lambda f: references & {n["deed_of_trust"] for n in f.notices if n.get("deed_of_trust")}),
            ("ts_number", lambda f: ts_key(event.get("ts_number")) and ts_key(event.get("ts_number")) in
             {ts_key(n.get("ts_number")) for n in f.notices}),
            ("apn", lambda f: event.get("apn") and event["apn"] in {n.get("apn") for n in f.notices})):
        found = [f for f in candidates if test(f)]
        if found:
            return max(found, key=lambda f: f.notice["recording_date"]), how
    return None, None


def link(notices: list[dict], cancellations: list[dict], deeds: list[dict]) -> tuple[dict[str, Foreclosure], list[dict]]:
    """Foreclosures with their events, and the events no notice in the data matched."""
    foreclosures = group_notices(notices)
    unlinked = []
    for kind, events in (("cancellation", cancellations), ("deed", deeds)):
        for event in sorted(events, key=lambda e: (e["recording_date"], e["recording_number"])):
            foreclosure, how = match(event, foreclosures)
            if foreclosure is None:
                unlinked.append({**event, "kind": kind})
                continue
            setattr(foreclosure, kind, event)
            foreclosure.links.append(f"{kind} {event['recording_number']} by {how}")
    for foreclosure in foreclosures.values():
        cancelled = foreclosure.cancellation
        if cancelled and not foreclosure.deed and foreclosure.notice["recording_date"] > cancelled["recording_date"]:
            foreclosure.cancellation = None  # re-noticed after the cancellation: open again
    return foreclosures, unlinked
