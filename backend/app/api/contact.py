"""The website's contact form.

Each message is saved first, then emailed to CONTACT_TO_EMAIL through Resend
(RESEND_API_KEY) from CONTACT_FROM_EMAIL, with the sender as reply-to so it
can be answered straight from the inbox. The form is public, so it has a
hidden honeypot field, length limits and a per-address rate limit.
"""
from __future__ import annotations

import logging
import os
import re
import time
from collections import defaultdict, deque
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.auth import verify_token
from app.database.session import engine

router = APIRouter(prefix="/api/v1", tags=["contact"])
logger = logging.getLogger(__name__)

TOPICS = {
    "general": "General question",
    "sales": "Plans and pricing",
    "enterprise": "Enterprise data",
    "support": "Account or billing support",
    "data": "Data correction",
}
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
LIMIT, WINDOW = 5, 3600  # messages per address per hour
_recent: dict[str, deque] = defaultdict(deque)


class ContactMessage(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=254)
    topic: Literal["general", "sales", "enterprise", "support", "data"] = "general"
    message: str = Field(min_length=10, max_length=5000)
    # Hidden in the form; people leave it empty, many bots fill it in.
    website: str = ""


def allowed(address: str, now: float | None = None) -> bool:
    now = now or time.time()
    recent = _recent[address]
    while recent and now - recent[0] > WINDOW:
        recent.popleft()
    if len(recent) >= LIMIT:
        return False
    recent.append(now)
    return True


def client_address(request: Request) -> str:
    # Behind Railway's proxy the client is the first X-Forwarded-For entry.
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")


def signed_in_user(request: Request) -> str | None:
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    try:
        return verify_token(token.strip()).get("sub")
    except HTTPException:
        return None


def send_email(message: ContactMessage) -> None:
    key, to = os.getenv("RESEND_API_KEY"), os.getenv("CONTACT_TO_EMAIL")
    if not key or not to:
        raise RuntimeError("RESEND_API_KEY or CONTACT_TO_EMAIL is not set")
    sender = os.getenv("CONTACT_FROM_EMAIL", "Sheriff Sale Hunter <noreply@mail.sheriffsalehunter.ai>")
    body = (f"New message from the Sheriff Sale Hunter contact form\n\n"
            f"Name: {message.name}\nEmail: {message.email}\nTopic: {TOPICS[message.topic]}\n\n{message.message}\n")
    response = httpx.post("https://api.resend.com/emails", timeout=20, headers={"Authorization": f"Bearer {key}"}, json={
        "from": sender, "to": [to], "reply_to": message.email,
        "subject": f"[Contact] {TOPICS[message.topic]}: {message.name}", "text": body})
    response.raise_for_status()


@router.post("/contact")
def contact(message: ContactMessage, request: Request) -> dict[str, bool]:
    if message.website:
        return {"received": True}  # honeypot: accept quietly, store nothing
    message.name, message.email, message.message = message.name.strip(), message.email.strip(), message.message.strip()
    if not EMAIL.match(message.email):
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    if not allowed(client_address(request)):
        raise HTTPException(status_code=429, detail="Too many messages. Please try again later or email us directly.")
    with engine.begin() as connection:
        message_id = connection.execute(text("""INSERT INTO contact_messages (name, email, topic, message, user_id)
            VALUES (:name, :email, :topic, :message, :user_id) RETURNING id"""),
            {"name": message.name, "email": message.email, "topic": message.topic, "message": message.message,
             "user_id": signed_in_user(request)}).scalar_one()
    try:
        send_email(message)
        status, error = "sent", None
    except Exception as exc:  # noqa: BLE001 - the message is saved; report delivery separately
        logger.warning("Contact email %s not sent: %s", message_id, exc)
        status, error = "failed", str(exc)[:500]
    with engine.begin() as connection:
        connection.execute(text("UPDATE contact_messages SET email_status=:status, email_error=:error WHERE id=:id"),
                           {"status": status, "error": error, "id": message_id})
    return {"received": True}
