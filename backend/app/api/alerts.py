"""One-click unsubscribe for opportunity alert emails.

Each email links to /api/v1/alerts/unsubscribe?u=<user id>&t=<signature>; the
signature is an HMAC of the user id with ALERTS_SIGNING_SECRET, so a link only
works for the person it was sent to. GET shows a confirmation page; POST is the
one-click form mail clients use (List-Unsubscribe-Post).
"""
from __future__ import annotations

import hashlib
import hmac
import os
from html import escape

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import text

from app.database.session import engine

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])
SITE_URL = os.getenv("SITE_URL", "https://www.sheriffsalehunter.ai").rstrip("/")


def signature(user_id: str) -> str:
    secret = os.getenv("ALERTS_SIGNING_SECRET")
    if not secret:
        raise RuntimeError("ALERTS_SIGNING_SECRET is not set")
    return hmac.new(secret.encode(), user_id.encode(), hashlib.sha256).hexdigest()


def unsubscribe_url(api_url: str, user_id: str) -> str:
    return f"{api_url.rstrip('/')}/api/v1/alerts/unsubscribe?u={user_id}&t={signature(user_id)}"


def _unsubscribe(user_id: str, token: str) -> None:
    try:
        valid = hmac.compare_digest(signature(user_id), token)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Unsubscribe is not configured.") from exc
    if not valid:
        raise HTTPException(status_code=400, detail="This unsubscribe link is not valid.")
    with engine.begin() as connection:
        connection.execute(text("""UPDATE investor_profiles SET email_alerts = FALSE, alert_frequency = NULL,
            email_alerts_consented_at = NULL, updated_at = NOW() WHERE user_id::text = :user_id"""), {"user_id": user_id})


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{escape(title)} · Sheriff Sale Hunter</title></head>
<body style="font-family:-apple-system,Segoe UI,Arial,sans-serif;background:#f6f7f5;margin:0;padding:48px 16px;color:#16202b">
<main style="max-width:520px;margin:auto;background:#fff;border:1px solid #e3e7ea;border-radius:8px;padding:32px">
<h1 style="font-size:24px;margin:0 0 12px">{escape(title)}</h1><p style="line-height:1.6;color:#4b5866">{body}</p>
<p><a href="{SITE_URL}/profile" style="color:#1f6b3a;font-weight:600">Manage your investor profile</a></p></main></body></html>""")


@router.get("/unsubscribe", response_class=HTMLResponse)
def unsubscribe_page(u: str = Query(max_length=64), t: str = Query(max_length=128)) -> HTMLResponse:
    _unsubscribe(u, t)
    return _page("You're unsubscribed", "You will no longer receive opportunity emails. "
                 "You can turn them back on any time from your investor profile.")


@router.post("/unsubscribe")
def unsubscribe_one_click(u: str = Query(max_length=64), t: str = Query(max_length=128)) -> dict[str, bool]:
    _unsubscribe(u, t)
    return {"unsubscribed": True}
