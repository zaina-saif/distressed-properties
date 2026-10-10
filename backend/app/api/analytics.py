"""Past-sale analytics: outcomes, winning bids against the asking price, and
how often third-party bidders win, for the sales in the user's coverage.

Winning bids and buyers come from pipeline/sale_results.py. A lender (the
plaintiff) usually takes a property back with a nominal bid such as $100, so
bid comparisons use third-party sales only.
"""
from __future__ import annotations

from datetime import date
from statistics import median
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text

from app.api.properties import MINIMUM_BID_SQL
from app.auth import Access, require_access
from app.database.session import engine
from app.rate_limit import per_user

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])

OUTCOMES = ("third_party", "plaintiff", "sold_other", "cancelled")
POSTPONEMENT_BUCKETS = ("0", "1", "2", "3", "4", "5+")


def _ratio(numerator: Any, denominator: Any) -> Optional[float]:
    if numerator is None or not denominator:
        return None
    return float(numerator) / float(denominator)


def _median(values: list[float]) -> Optional[float]:
    return median(values) if values else None


@router.get("/sales", dependencies=[Depends(per_user("analytics", 300))])
def sale_analytics(
    state: list[str] = Query(default=[]),
    county: list[str] = Query(default=[]),
    months: Optional[int] = Query(default=None, ge=1, le=120, description="Only sales in the last N months"),
    access: Access = Depends(require_access),
):
    conditions = ["outcome_date <= CURRENT_DATE"]
    parameters: dict[str, Any] = {}
    # The plan's coverage always applies, on top of any filters in the request.
    if access.scope_state:
        conditions.append("state = :scope_state")
        parameters["scope_state"] = access.scope_state
    if access.scope_county:
        conditions.append("LOWER(county) = :scope_county")
        parameters["scope_county"] = access.scope_county.lower()
    if state:
        conditions.append("state = ANY(:states)")
        parameters["states"] = [value.upper() for value in state]
    if county:
        conditions.append("LOWER(county) = ANY(:counties)")
        parameters["counties"] = [value.lower() for value in county]
    if months:
        conditions.append("outcome_date >= CURRENT_DATE - make_interval(months => :months)")
        parameters["months"] = months

    with engine.connect() as connection:
        rows = connection.execute(text(f"""
            WITH completed AS (
                SELECT ss.id, ss.state, ss.county, p.street_address, p.city,
                       CASE
                           WHEN ss.current_status ILIKE 'cancel%' THEN 'cancelled'
                           WHEN ss.sold_buyer IN ('third_party', 'plaintiff') THEN ss.sold_buyer
                           ELSE 'sold_other'
                       END AS outcome,
                       COALESCE(ss.sold_on, ss.current_sale_date::date) AS outcome_date,
                       ss.sold_amount,
                       {MINIMUM_BID_SQL} AS ask,
                       (SELECT COUNT(*) FROM sheriff_sale_status_history h
                        WHERE h.sheriff_sale_id = ss.id AND h.status IN ('adjourned', 'postponed')) AS postponements
                FROM sheriff_sales ss
                LEFT JOIN properties p ON p.id = ss.property_id
                WHERE ss.current_status NOT ILIKE '%unverified%'
                  AND (ss.sold_buyer IS NOT NULL OR ss.current_status ILIKE 'cancel%'
                       OR ss.current_status ILIKE 'sold%' OR ss.current_status ILIKE 'purchased%')
            )
            SELECT * FROM completed
            WHERE {' AND '.join(conditions)}
            ORDER BY outcome_date DESC
        """), parameters).mappings().all()

    by_month: dict[str, dict[str, int]] = {}
    by_county: dict[tuple[str, str], dict[str, Any]] = {}
    postponements = {bucket: 0 for bucket in POSTPONEMENT_BUCKETS}
    points: list[dict[str, Any]] = []
    bid_to_ask: list[float] = []
    for row in rows:
        outcome = row["outcome"]
        month = by_month.setdefault(row["outcome_date"].strftime("%Y-%m"), {name: 0 for name in OUTCOMES})
        month[outcome] += 1
        place = by_county.setdefault((row["state"], row["county"]), {
            "state": row["state"], "county": row["county"], **{name: 0 for name in OUTCOMES}, "ratios": []})
        place[outcome] += 1
        if outcome != "cancelled":
            count = int(row["postponements"] or 0)
            postponements[str(count) if count < 5 else "5+"] += 1
        ratio = _ratio(row["sold_amount"], row["ask"])
        if outcome == "third_party" and ratio is not None:
            bid_to_ask.append(ratio)
            place["ratios"].append(ratio)
            points.append({
                "sale_id": str(row["id"]), "address": row["street_address"], "city": row["city"],
                "state": row["state"], "county": row["county"], "sold_on": row["outcome_date"].isoformat(),
                "ask": float(row["ask"]), "winning_bid": float(row["sold_amount"]), "bid_to_ask": ratio,
            })

    def sold(item: dict[str, Any]) -> int:
        return item["third_party"] + item["plaintiff"] + item["sold_other"]

    totals = {name: sum(month[name] for month in by_month.values()) for name in OUTCOMES}
    known_buyer = totals["third_party"] + totals["plaintiff"]
    counties = []
    for place in by_county.values():
        ratios = place.pop("ratios")
        buyers = place["third_party"] + place["plaintiff"]
        counties.append({**place, "sold": sold(place),
                         "third_party_rate": place["third_party"] / buyers if buyers else None,
                         "median_bid_to_ask": _median(ratios)})
    counties.sort(key=lambda item: (-(item["third_party"] + item["plaintiff"]), item["state"], item["county"]))

    return {
        "as_of": date.today().isoformat(),
        "summary": {
            "completed": len(rows),
            "sold": sold(totals),
            **totals,
            # Share of sales with a known buyer that a third-party bidder won.
            "third_party_rate": totals["third_party"] / known_buyer if known_buyer else None,
            "median_bid_to_ask": _median(bid_to_ask),
            "median_winning_bid": _median([point["winning_bid"] for point in points]),
            "third_party_volume": sum(point["winning_bid"] for point in points),
            "priced_sales": len(points),
        },
        "months": [{"month": key, **value} for key, value in sorted(by_month.items())],
        "counties": counties,
        "postponements": [{"postponements": bucket, "sales": postponements[bucket]} for bucket in POSTPONEMENT_BUCKETS],
        "points": points,
    }
