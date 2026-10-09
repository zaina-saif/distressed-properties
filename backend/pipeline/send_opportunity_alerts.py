"""Email investors new sales that match their investor profile.

Only users who opted in (investor_profiles.email_alerts) and have an active
plan are emailed, and only about sales inside their plan's coverage. Each
sale is sent to a user at most once (opportunity_alert_items).

Matching: upcoming scheduled sales in the profile's states (or every state the
plan covers), within the budget (minimum bid, or estimated value when no bid
is known), with at least the profile's minimum gross equity, and of the chosen
property types (Zillow home type). Up to 15 per email, largest equity first.

    python -m pipeline.send_opportunity_alerts --frequency daily --dry-run
    python -m pipeline.send_opportunity_alerts --frequency weekly

Settings: RESEND_API_KEY, ALERTS_SIGNING_SECRET, ALERTS_POSTAL_ADDRESS
(required by CAN-SPAM; sending stops without it), ALERTS_FROM_EMAIL,
SITE_URL and API_URL.
"""
from __future__ import annotations

import argparse
import os
import time
from html import escape
from urllib.parse import urlencode

import httpx
from sqlalchemy import text

from app.api.alerts import unsubscribe_url
from app.api.properties import EFFECTIVE_STATUS_SQL, MINIMUM_BID_SQL
from app.auth import Access
from app.database.session import engine

SITE_URL = os.getenv("SITE_URL", "https://www.sheriffsalehunter.ai").rstrip("/")
API_URL = os.getenv("API_URL", "https://api.sheriffsalehunter.ai").rstrip("/")
FROM = os.getenv("ALERTS_FROM_EMAIL", "Sheriff Sale Hunter <alerts@mail.sheriffsalehunter.ai>")
PER_EMAIL = 15

BUDGET = {"under_100k": (0, 100_000), "100k_250k": (100_000, 250_000), "250k_500k": (250_000, 500_000),
          "500k_1m": (500_000, 1_000_000), "over_1m": (1_000_000, None)}
MIN_EQUITY = {"any": None, "25k": 25_000, "50k": 50_000, "100k": 100_000}
HOME_TYPES = {"single_family": ["SINGLE_FAMILY", "MANUFACTURED"], "multi_2_4": ["MULTI_FAMILY"],
              "multi_5_plus": ["MULTI_FAMILY"], "condo_townhouse": ["CONDO", "TOWNHOUSE", "APARTMENT"],
              "land": ["LOT"], "commercial": []}


def subscribers(frequency: str) -> list[dict]:
    with engine.connect() as connection:
        return [dict(row) for row in connection.execute(text("""
            SELECT p.user_id::text, a.email, a.role, a.plan, a.plan_status, a.coverage_state, a.coverage_county,
                   p.budget_range, p.states, p.property_types, p.min_equity
            FROM investor_profiles p JOIN user_accounts a ON a.user_id = p.user_id
            WHERE p.email_alerts AND p.alert_frequency = :frequency
        """), {"frequency": frequency}).mappings()]


def criteria(profile: dict) -> tuple[str, dict]:
    """SQL conditions and parameters for one subscriber's matches."""
    access = Access(profile["user_id"], profile["email"], role=profile["role"], plan=profile["plan"],
                    plan_status=profile["plan_status"], coverage_state=profile["coverage_state"],
                    coverage_county=profile["coverage_county"])
    conditions = [f"strpos({EFFECTIVE_STATUS_SQL}, 'scheduled') > 0", "ss.current_sale_date >= CURRENT_DATE",
                  "ss.property_id IS NOT NULL",
                  "NOT EXISTS (SELECT 1 FROM opportunity_alert_items i WHERE i.user_id = CAST(:user_id AS UUID) "
                  "AND i.sheriff_sale_id = ss.id)"]
    params: dict = {"user_id": profile["user_id"]}
    # Plan coverage always applies; the profile's states narrow it further.
    if access.scope_state:
        conditions.append("p.state = :scope_state")
        params["scope_state"] = access.scope_state
    if access.scope_county:
        conditions.append("LOWER(p.county) = :scope_county")
        params["scope_county"] = access.scope_county.lower()
    if profile["states"]:
        conditions.append("p.state = ANY(:states)")
        params["states"] = list(profile["states"])
    price = f"COALESCE({MINIMUM_BID_SQL}, azr.zestimate)"
    low, high = BUDGET.get(profile["budget_range"] or "", (None, None))
    if low:
        conditions.append(f"{price} >= :budget_low")
        params["budget_low"] = low
    if high:
        conditions.append(f"{price} <= :budget_high")
        params["budget_high"] = high
    minimum = MIN_EQUITY.get(profile["min_equity"] or "any")
    if minimum:
        conditions.append(f"(azr.zestimate - {MINIMUM_BID_SQL}) >= :min_equity")
        params["min_equity"] = minimum
    if profile["property_types"]:
        types = sorted({home for choice in profile["property_types"] for home in HOME_TYPES.get(choice, [])})
        conditions.append("azr.raw_payload->>'homeType' = ANY(:home_types)")
        params["home_types"] = types or ["__none__"]
    return " AND ".join(conditions), params


def matches(profile: dict) -> list[dict]:
    where, params = criteria(profile)
    with engine.connect() as connection:
        return [dict(row) for row in connection.execute(text(f"""
            SELECT ss.id::text AS sale_id, p.street_address, p.city, p.state, p.county, ss.current_sale_date,
                   azr.zestimate, {MINIMUM_BID_SQL} AS minimum_bid, (azr.zestimate - {MINIMUM_BID_SQL}) AS gross_equity
            FROM sheriff_sales ss JOIN properties p ON p.id = ss.property_id
            LEFT JOIN LATERAL (SELECT zestimate, raw_payload FROM apify_zillow_results
                WHERE property_id = ss.property_id AND is_current AND match_status <> 'invalid'
                ORDER BY retrieved_at DESC LIMIT 1) azr ON TRUE
            WHERE {where}
            ORDER BY (azr.zestimate - {MINIMUM_BID_SQL}) DESC NULLS LAST, ss.current_sale_date
            LIMIT {PER_EMAIL}
        """), params).mappings()]


def money(value) -> str:
    return f"${float(value):,.0f}" if value is not None else "Not published"


def render(profile: dict, sales: list[dict], postal_address: str) -> tuple[str, str, str]:
    """Subject, HTML and plain-text bodies."""
    subject = f"{len(sales)} new sale{'s' if len(sales) != 1 else ''} matching your investor profile"
    unsubscribe = unsubscribe_url(API_URL, profile["user_id"])
    rows_html, rows_text = [], []
    for sale in sales:
        link = f"{SITE_URL}/dashboard?{urlencode({'state': sale['state'], 'q': sale['street_address']})}"
        place = f"{sale['city']}, {sale['state']} · {sale['county']} County"
        date = sale["current_sale_date"].strftime("%b %-d, %Y") if sale["current_sale_date"] else "Date to be confirmed"
        rows_html.append(f"""<tr><td style="padding:14px 0;border-bottom:1px solid #e3e7ea">
<a href="{escape(link)}" style="font-size:16px;font-weight:600;color:#16202b;text-decoration:none">{escape(sale['street_address'])}</a>
<div style="font-size:13px;color:#5b6773;margin-top:2px">{escape(place)} · Sale {escape(date)}</div>
<div style="font-size:13px;margin-top:6px">Estimated value <b>{money(sale['zestimate'])}</b> · Minimum bid <b>{money(sale['minimum_bid'])}</b>
· Est. gross equity <b style="color:#1f6b3a">{money(sale['gross_equity'])}</b></div></td></tr>""")
        rows_text.append(f"- {sale['street_address']}, {place}. Sale {date}. Value {money(sale['zestimate'])}, "
                         f"minimum bid {money(sale['minimum_bid'])}, est. gross equity {money(sale['gross_equity'])}.\n  {link}")
    footer_text = (f"Estimates are not guaranteed; verify every property, its liens and the sale details before bidding.\n"
                   f"You receive this because you turned on opportunity emails in your investor profile.\n"
                   f"Manage preferences: {SITE_URL}/profile\nUnsubscribe: {unsubscribe}\n{postal_address}\n")
    html = f"""<!doctype html><html><body style="margin:0;background:#f6f7f5;font-family:-apple-system,Segoe UI,Arial,sans-serif;color:#16202b">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:24px 12px">
<table role="presentation" width="100%" style="max-width:600px;background:#fff;border:1px solid #e3e7ea;border-radius:8px" cellpadding="0" cellspacing="0">
<tr><td style="padding:24px 28px 8px"><div style="font-size:12px;font-weight:700;color:#1f6b3a;letter-spacing:.04em">SHERIFF SALE HUNTER</div>
<h1 style="font-size:20px;margin:8px 0 4px">{escape(subject)}</h1>
<p style="font-size:13px;color:#5b6773;margin:0">Upcoming sales that fit the budget, markets and property types in your profile.</p></td></tr>
<tr><td style="padding:0 28px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0">{''.join(rows_html)}</table></td></tr>
<tr><td style="padding:20px 28px"><a href="{SITE_URL}/dashboard" style="display:inline-block;background:#16202b;color:#fff;text-decoration:none;padding:11px 18px;border-radius:4px;font-size:14px;font-weight:600">Open the dashboard</a></td></tr>
<tr><td style="padding:16px 28px 24px;border-top:1px solid #e3e7ea;font-size:11px;line-height:1.6;color:#7a8692">
Estimates are not guaranteed. Verify every property, its liens and the current sale details with the original source before bidding; this is not legal or title advice.<br>
You receive this email because you turned on opportunity emails in your investor profile.
<a href="{SITE_URL}/profile" style="color:#1f6b3a">Manage preferences</a> · <a href="{escape(unsubscribe)}" style="color:#1f6b3a">Unsubscribe</a><br>
{escape(postal_address)}</td></tr></table></td></tr></table></body></html>"""
    text_body = f"{subject}\n\n" + "\n".join(rows_text) + f"\n\nOpen the dashboard: {SITE_URL}/dashboard\n\n{footer_text}"
    return subject, html, text_body


def send(profile: dict, subject: str, html: str, text_body: str) -> None:
    unsubscribe = unsubscribe_url(API_URL, profile["user_id"])
    response = httpx.post("https://api.resend.com/emails", timeout=30,
                          headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"}, json={
        "from": FROM, "to": [profile["email"]], "subject": subject, "html": html, "text": text_body,
        "headers": {"List-Unsubscribe": f"<{unsubscribe}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}})
    response.raise_for_status()


def record(profile: dict, sales: list[dict]) -> None:
    with engine.begin() as connection:
        for sale in sales:
            connection.execute(text("""INSERT INTO opportunity_alert_items (user_id, sheriff_sale_id)
                VALUES (CAST(:user_id AS UUID), CAST(:sale_id AS UUID)) ON CONFLICT DO NOTHING"""),
                {"user_id": profile["user_id"], "sale_id": sale["sale_id"]})
        connection.execute(text("UPDATE investor_profiles SET last_alert_sent_at = NOW() WHERE user_id = CAST(:u AS UUID)"),
                           {"u": profile["user_id"]})


def run(frequency: str, dry_run: bool) -> dict[str, int]:
    postal_address = os.getenv("ALERTS_POSTAL_ADDRESS", "").strip()
    if not dry_run:
        missing = [name for name in ("RESEND_API_KEY", "ALERTS_SIGNING_SECRET") if not os.getenv(name)]
        if not postal_address:
            missing.append("ALERTS_POSTAL_ADDRESS")
        if missing:
            raise SystemExit(f"Not sending: set {', '.join(missing)}")
    counts = {"subscribers": 0, "no_plan": 0, "no_matches": 0, "sent": 0, "failed": 0}
    for profile in subscribers(frequency):
        counts["subscribers"] += 1
        access = Access(profile["user_id"], profile["email"], role=profile["role"], plan=profile["plan"],
                        plan_status=profile["plan_status"], coverage_state=profile["coverage_state"],
                        coverage_county=profile["coverage_county"])
        if not access.has_plan:
            counts["no_plan"] += 1
            continue
        sales = matches(profile)
        if not sales:
            counts["no_matches"] += 1
            continue
        if dry_run:
            print(f"would email user {profile['user_id'][:8]}… {len(sales)} sales: "
                  + "; ".join(f"{s['street_address']}, {s['state']}" for s in sales[:3]))
            counts["sent"] += 1
            continue
        try:
            send(profile, *render(profile, sales, postal_address))
            record(profile, sales)
            counts["sent"] += 1
        except Exception as exc:  # noqa: BLE001 - one failed email must not stop the rest
            print(f"failed for user {profile['user_id'][:8]}…: {type(exc).__name__}: {exc}")
            counts["failed"] += 1
        time.sleep(0.6)  # stay under Resend's request rate
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--frequency", choices=["daily", "weekly"], required=True)
    parser.add_argument("--dry-run", action="store_true", help="List who would get what; send and record nothing")
    args = parser.parse_args()
    counts = run(args.frequency, args.dry_run)
    print(counts)
    if counts["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
