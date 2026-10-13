"""Email free-trial users before and when their 7-day trial ends.

Two emails per trial, each sent once (user_accounts.trial_reminder_sent_at and
trial_ended_sent_at):
  reminder  the trial ends within REMIND_HOURS
  ended     the trial has ended and the account has not picked a plan

Both tell them how to keep access: stay free with one county in a state, or
take Starter (one state) or Pro (every state). Run daily:

    python -m pipeline.send_trial_reminders --dry-run
    python -m pipeline.send_trial_reminders

Settings: RESEND_API_KEY, ALERTS_POSTAL_ADDRESS (sending stops without it),
ALERTS_FROM_EMAIL and SITE_URL, as for pipeline.send_opportunity_alerts.
"""
from __future__ import annotations

import argparse
import os
import time
from html import escape

import httpx
from sqlalchemy import text

from app.database.session import engine

SITE_URL = os.getenv("SITE_URL", "https://www.sheriffsalehunter.ai").rstrip("/")
FROM = os.getenv("ALERTS_FROM_EMAIL", "Sheriff Sale Hunter <alerts@mail.sheriffsalehunter.ai>")
REMIND_HOURS = 48
# Monthly prices; keep in step with plans() in frontend/src/components/pricing-page.tsx.
PLANS = [
    ("Free", "$0", "One county of your choice, free for as long as you like"),
    ("Starter", "$19.99/mo", "Every county in one state, auction odds, lien pre-screening and Investor Spotlight"),
    ("Pro", "$49.99/mo", "Every state and county we cover, Excel export and one map across states"),
]


def due() -> list[dict]:
    """Trial accounts owed an email, with which one ('reminder' or 'ended')."""
    with engine.connect() as connection:
        return [dict(row) for row in connection.execute(text("""
            SELECT user_id::text, email, trial_ends_at,
                   CASE WHEN trial_ends_at <= NOW() THEN 'ended' ELSE 'reminder' END AS kind
            FROM user_accounts
            WHERE plan = 'trial' AND role <> 'developer' AND trial_ends_at IS NOT NULL AND (
                (trial_ends_at <= NOW() AND trial_ended_sent_at IS NULL)
                OR (trial_ends_at > NOW() AND trial_ends_at <= NOW() + make_interval(hours => :hours)
                    AND trial_reminder_sent_at IS NULL))
            ORDER BY trial_ends_at
        """), {"hours": REMIND_HOURS}).mappings()]


def render(account: dict, postal_address: str) -> tuple[str, str, str]:
    """Subject, HTML and plain-text bodies."""
    ends = account["trial_ends_at"].strftime("%A, %b %-d")
    choose = f"{SITE_URL}/choose-plan"
    if account["kind"] == "ended":
        subject = "Your free trial has ended: keep exploring for free"
        intro = ("Your 7-day free trial of Sheriff Sale Hunter has ended. You can keep going for free: "
                 "choose one county within a state and it stays free. Or pick a paid plan to work a whole state or every state.")
    else:
        subject = f"Your free trial ends {ends}"
        intro = (f"Your 7-day free trial of Sheriff Sale Hunter ends on {ends}. To keep access, choose a plan. "
                 "If you want to stay free, you can: pick one county within a state on the Free plan. "
                 "Paid plans open a whole state or every state we cover.")
    rows_html = "".join(f"""<tr><td style="padding:10px 0;border-bottom:1px solid #e3e7ea">
<b style="font-size:15px">{escape(name)}</b> <span style="color:#1f6b3a;font-weight:600">{escape(price)}</span>
<div style="font-size:13px;color:#5b6773;margin-top:2px">{escape(detail)}</div></td></tr>""" for name, price, detail in PLANS)
    rows_text = "\n".join(f"- {name} ({price}): {detail}" for name, price, detail in PLANS)
    html = f"""<!doctype html><html><body style="margin:0;background:#f6f7f5;font-family:-apple-system,Segoe UI,Arial,sans-serif;color:#16202b">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:24px 12px">
<table role="presentation" width="100%" style="max-width:600px;background:#fff;border:1px solid #e3e7ea;border-radius:8px" cellpadding="0" cellspacing="0">
<tr><td style="padding:24px 28px 8px"><div style="font-size:12px;font-weight:700;color:#1f6b3a;letter-spacing:.04em">SHERIFF SALE HUNTER</div>
<h1 style="font-size:20px;margin:8px 0 8px">{escape(subject)}</h1>
<p style="font-size:14px;line-height:1.5;color:#36414c;margin:0">{escape(intro)}</p></td></tr>
<tr><td style="padding:8px 28px 0"><table role="presentation" width="100%" cellpadding="0" cellspacing="0">{rows_html}</table></td></tr>
<tr><td style="padding:20px 28px"><a href="{choose}" style="display:inline-block;background:#16202b;color:#fff;text-decoration:none;padding:11px 18px;border-radius:4px;font-size:14px;font-weight:600">Choose my plan</a></td></tr>
<tr><td style="padding:16px 28px 24px;border-top:1px solid #e3e7ea;font-size:11px;line-height:1.6;color:#7a8692">
You receive this email because you started a free trial at Sheriff Sale Hunter. No card was taken and nothing is charged unless you choose a paid plan.<br>
{escape(postal_address)}</td></tr></table></td></tr></table></body></html>"""
    text_body = (f"{subject}\n\n{intro}\n\n{rows_text}\n\nChoose my plan: {choose}\n\n"
                 "You receive this email because you started a free trial at Sheriff Sale Hunter. "
                 f"No card was taken and nothing is charged unless you choose a paid plan.\n{postal_address}\n")
    return subject, html, text_body


def send(account: dict, subject: str, html: str, text_body: str) -> None:
    response = httpx.post("https://api.resend.com/emails", timeout=30,
                          headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"},
                          json={"from": FROM, "to": [account["email"]], "subject": subject, "html": html, "text": text_body})
    response.raise_for_status()


def record(account: dict) -> None:
    # An "ended" email also stands in for a reminder that was never sent.
    column = "trial_ended_sent_at = NOW(), trial_reminder_sent_at = COALESCE(trial_reminder_sent_at, NOW())" \
        if account["kind"] == "ended" else "trial_reminder_sent_at = NOW()"
    with engine.begin() as connection:
        connection.execute(text(f"UPDATE user_accounts SET {column} WHERE user_id = CAST(:u AS UUID)"),
                           {"u": account["user_id"]})


def run(dry_run: bool) -> dict[str, int]:
    postal_address = os.getenv("ALERTS_POSTAL_ADDRESS", "").strip()
    if not dry_run:
        missing = [name for name in ("RESEND_API_KEY",) if not os.getenv(name)]
        if not postal_address:
            missing.append("ALERTS_POSTAL_ADDRESS")
        if missing:
            raise SystemExit(f"Not sending: set {', '.join(missing)}")
    counts = {"reminder": 0, "ended": 0, "failed": 0}
    for account in due():
        if dry_run:
            print(f"would email user {account['user_id'][:8]}… {account['kind']} (trial ends {account['trial_ends_at']:%Y-%m-%d %H:%M} UTC)")
            counts[account["kind"]] += 1
            continue
        try:
            send(account, *render(account, postal_address))
            record(account)
            counts[account["kind"]] += 1
        except Exception as exc:  # noqa: BLE001 - one failed email must not stop the rest
            print(f"failed for user {account['user_id'][:8]}…: {type(exc).__name__}: {exc}")
            counts["failed"] += 1
        time.sleep(0.6)  # stay under Resend's request rate
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="List who would get which email; send and record nothing")
    counts = run(parser.parse_args().dry_run)
    print(counts)
    if counts["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
