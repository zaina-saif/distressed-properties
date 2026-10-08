"""Accounts and billing: the signed-in user's plan, the Free plan, Stripe
Checkout for Starter and Pro, the Stripe customer portal, and the Stripe
webhook that keeps plans in step with subscriptions.

Stripe settings (environment):
  STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET
  STRIPE_PRICE_STARTER_MONTH, STRIPE_PRICE_STARTER_YEAR,
  STRIPE_PRICE_PRO_MONTH, STRIPE_PRICE_PRO_YEAR
  FRONTEND_URL  where Checkout and the portal send people back to
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text

from app.auth import Access, current_user
from app.database.session import engine

router = APIRouter(prefix="/api/v1", tags=["account"])

# States with sale listings; plan coverage must be one of these.
SUPPORTED_STATES = {"NJ", "PA", "OH", "FL", "IL", "SC", "DE", "CO", "MN", "LA", "IA", "WA", "KS", "ID", "OR", "AZ", "AR", "CT"}
COVERAGE_CHANGE_DAYS = 30
# Stripe subscription status -> plan_status.
STATUS = {"active": "active", "trialing": "trialing", "past_due": "past_due", "unpaid": "past_due",
          "canceled": "canceled", "incomplete": "inactive", "incomplete_expired": "inactive", "paused": "inactive"}


def price_ids() -> dict[tuple[str, str], str]:
    prices = {(plan, interval): os.getenv(f"STRIPE_PRICE_{plan.upper()}_{interval.upper()}", "")
              for plan in ("starter", "pro") for interval in ("month", "year")}
    return {key: value for key, value in prices.items() if value}


def plan_for_price(price_id: str | None) -> tuple[str, str] | None:
    return next((key for key, value in price_ids().items() if value == price_id), None)


def stripe_client() -> None:
    key = os.getenv("STRIPE_SECRET_KEY")
    if not key:
        raise HTTPException(status_code=503, detail="Billing is not configured on this server.")
    stripe.api_key = key


def frontend_url() -> str:
    return os.getenv("FRONTEND_URL", "http://localhost:3000").rstrip("/")


def account_row(user_id: str) -> dict[str, Any]:
    with engine.connect() as connection:
        return dict(connection.execute(text("""
            SELECT user_id::text, email, role, plan, plan_status, billing_interval, coverage_state, coverage_county,
                   coverage_changed_at, stripe_customer_id, stripe_subscription_id, current_period_end
            FROM user_accounts WHERE user_id = :user_id
        """), {"user_id": user_id}).mappings().one())


def check_coverage(state: str, county: str | None) -> tuple[str, str | None]:
    """A supported state and, if given, a county there with sale listings."""
    state = state.strip().upper()
    if state not in SUPPORTED_STATES:
        raise HTTPException(status_code=400, detail=f"{state} is not a covered state.")
    if county is None:
        return state, None
    with engine.connect() as connection:
        match = connection.execute(text("""
            SELECT p.county FROM sheriff_sales ss JOIN properties p ON p.id = ss.property_id
            WHERE p.state = :state AND LOWER(p.county) = LOWER(:county) LIMIT 1
        """), {"state": state, "county": county.strip()}).scalar()
    if not match:
        raise HTTPException(status_code=400, detail=f"{county} is not a covered county in {state}.")
    return state, match


@router.get("/account/me")
def me(access: Access = Depends(current_user)) -> dict[str, Any]:
    row = account_row(access.user_id)
    return {
        "email": row["email"], "role": row["role"], "plan": row["plan"], "plan_status": row["plan_status"],
        "billing_interval": row["billing_interval"], "coverage_state": row["coverage_state"],
        "coverage_county": row["coverage_county"], "current_period_end": row["current_period_end"],
        "has_access": access.has_plan, "is_developer": access.is_developer,
        "has_billing": bool(row["stripe_customer_id"]),
        "coverage_change_available_at": (row["coverage_changed_at"] + timedelta(days=COVERAGE_CHANGE_DAYS))
        if row["coverage_changed_at"] else None,
        "paid_plans_available": sorted({plan for plan, _ in price_ids()}),
    }


class FreePlan(BaseModel):
    state: str
    county: str


@router.post("/account/free-plan")
def start_free_plan(body: FreePlan, access: Access = Depends(current_user)) -> dict[str, Any]:
    row = account_row(access.user_id)
    if row["plan"] in ("starter", "pro") and row["plan_status"] in ("active", "trialing", "past_due"):
        raise HTTPException(status_code=409, detail="You have a paid plan. Manage it from billing instead.")
    state, county = check_coverage(body.state, body.county)
    with engine.begin() as connection:
        connection.execute(text("""
            UPDATE user_accounts SET plan='free', plan_status='active', coverage_state=:state, coverage_county=:county,
                coverage_changed_at=NOW(), updated_at=NOW() WHERE user_id=:user_id
        """), {"state": state, "county": county, "user_id": access.user_id})
    return {"plan": "free", "coverage_state": state, "coverage_county": county}


class Coverage(BaseModel):
    state: str
    county: Optional[str] = None


@router.post("/account/coverage")
def change_coverage(body: Coverage, access: Access = Depends(current_user)) -> dict[str, Any]:
    """Free picks a county, Starter a state; either can change once every 30 days."""
    row = account_row(access.user_id)
    if access.is_developer or row["plan"] == "pro":
        raise HTTPException(status_code=400, detail="Your plan already covers every state.")
    if row["plan"] not in ("free", "starter"):
        raise HTTPException(status_code=402, detail="Choose a plan first.")
    if row["plan"] == "free" and not body.county:
        raise HTTPException(status_code=400, detail="The Free plan covers one county; choose a county.")
    changed = row["coverage_changed_at"]
    if changed and datetime.now(timezone.utc) - changed < timedelta(days=COVERAGE_CHANGE_DAYS):
        available = (changed + timedelta(days=COVERAGE_CHANGE_DAYS)).date().isoformat()
        raise HTTPException(status_code=429, detail=f"You can change your coverage again on {available}.")
    state, county = check_coverage(body.state, body.county if row["plan"] == "free" else None)
    with engine.begin() as connection:
        connection.execute(text("""
            UPDATE user_accounts SET coverage_state=:state, coverage_county=:county, coverage_changed_at=NOW(),
                updated_at=NOW() WHERE user_id=:user_id
        """), {"state": state, "county": county, "user_id": access.user_id})
    return {"coverage_state": state, "coverage_county": county}


class Checkout(BaseModel):
    plan: Literal["starter", "pro"]
    interval: Literal["month", "year"] = "month"
    state: Optional[str] = None


@router.post("/billing/checkout")
def create_checkout(body: Checkout, access: Access = Depends(current_user)) -> dict[str, str]:
    stripe_client()
    price = price_ids().get((body.plan, body.interval))
    if not price:
        raise HTTPException(status_code=503, detail=f"The {body.plan} plan is not available for purchase yet.")
    if body.plan == "starter" and not body.state:
        raise HTTPException(status_code=400, detail="The Starter plan covers one state; choose a state.")
    state = check_coverage(body.state, None)[0] if body.plan == "starter" else None
    row = account_row(access.user_id)
    if row["stripe_subscription_id"] and row["plan_status"] in ("active", "trialing", "past_due"):
        raise HTTPException(status_code=409, detail="You already have a subscription. Change it from billing.")
    customer = row["stripe_customer_id"]
    if not customer:
        customer = stripe.Customer.create(email=access.email, metadata={"user_id": access.user_id}).id
        with engine.begin() as connection:
            connection.execute(text("UPDATE user_accounts SET stripe_customer_id=:customer WHERE user_id=:user_id"),
                               {"customer": customer, "user_id": access.user_id})
    metadata = {"user_id": access.user_id, "plan": body.plan, "interval": body.interval, "coverage_state": state or ""}
    session = stripe.checkout.Session.create(
        mode="subscription", customer=customer, client_reference_id=access.user_id,
        line_items=[{"price": price, "quantity": 1}], metadata=metadata,
        subscription_data={"metadata": metadata}, allow_promotion_codes=True,
        success_url=f"{frontend_url()}/account?checkout=success",
        cancel_url=f"{frontend_url()}/choose-plan?checkout=cancelled",
    )
    return {"url": session.url}


@router.post("/billing/portal")
def create_portal(access: Access = Depends(current_user)) -> dict[str, str]:
    stripe_client()
    customer = account_row(access.user_id)["stripe_customer_id"]
    if not customer:
        raise HTTPException(status_code=400, detail="There is no billing account yet.")
    session = stripe.billing_portal.Session.create(customer=customer, return_url=f"{frontend_url()}/account")
    return {"url": session.url}


def _period_end(subscription: dict[str, Any]) -> datetime | None:
    # Newer Stripe API versions keep the period on each subscription item.
    value = subscription.get("current_period_end")
    if value is None:
        items = (subscription.get("items") or {}).get("data") or []
        value = items[0].get("current_period_end") if items else None
    return datetime.fromtimestamp(value, timezone.utc) if value else None


def apply_subscription(subscription: dict[str, Any]) -> None:
    """Copy a subscription's plan, status and period onto its user's account."""
    items = (subscription.get("items") or {}).get("data") or []
    price = items[0].get("price", {}).get("id") if items else None
    plan_interval = plan_for_price(price)
    metadata = subscription.get("metadata") or {}
    status = STATUS.get(subscription.get("status") or "", "inactive")
    params = {
        "user_id": metadata.get("user_id") or None, "customer": subscription.get("customer"),
        "subscription": subscription.get("id"), "status": status, "period_end": _period_end(subscription),
        "plan": plan_interval[0] if plan_interval else metadata.get("plan"),
        "interval": plan_interval[1] if plan_interval else metadata.get("interval"),
        "coverage_state": metadata.get("coverage_state") or None,
    }
    if status == "canceled":
        params["plan"] = "none"
    with engine.begin() as connection:
        connection.execute(text("""
            UPDATE user_accounts SET
                plan = COALESCE(:plan, plan), plan_status = :status, billing_interval = COALESCE(:interval, billing_interval),
                stripe_customer_id = COALESCE(:customer, stripe_customer_id), stripe_subscription_id = :subscription,
                current_period_end = :period_end,
                -- Starter's state comes from checkout; keep a state chosen later.
                coverage_state = CASE WHEN :plan = 'starter' THEN COALESCE(coverage_state, :coverage_state)
                                      WHEN :plan = 'pro' THEN NULL ELSE coverage_state END,
                coverage_county = CASE WHEN :plan IN ('starter', 'pro') THEN NULL ELSE coverage_county END,
                coverage_changed_at = CASE WHEN :plan = 'starter' AND coverage_state IS NULL THEN NOW()
                                           ELSE coverage_changed_at END,
                updated_at = NOW()
            WHERE user_id::text = :user_id OR stripe_customer_id = :customer OR stripe_subscription_id = :subscription
        """), params)


@router.post("/billing/webhook", include_in_schema=False)
async def stripe_webhook(request: Request) -> dict[str, bool]:
    secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(status_code=503, detail="Billing is not configured on this server.")
    try:
        event = stripe.Webhook.construct_event(await request.body(), request.headers.get("Stripe-Signature", ""), secret)
    except (ValueError, stripe.SignatureVerificationError) as exc:
        raise HTTPException(status_code=400, detail="Invalid Stripe signature") from exc
    with engine.begin() as connection:
        new = connection.execute(text("""INSERT INTO stripe_events (id, type) VALUES (:id, :type)
            ON CONFLICT (id) DO NOTHING RETURNING id"""), {"id": event["id"], "type": event["type"]}).scalar()
    if not new:
        return {"received": True}
    data = event["data"]["object"]
    if event["type"] == "checkout.session.completed" and data.get("subscription"):
        stripe_client()
        subscription = stripe.Subscription.retrieve(data["subscription"])
        apply_subscription(subscription.to_dict() if hasattr(subscription, "to_dict") else dict(subscription))
    elif event["type"] in ("customer.subscription.created", "customer.subscription.updated",
                           "customer.subscription.deleted"):
        apply_subscription(data.to_dict() if hasattr(data, "to_dict") else dict(data))
    return {"received": True}
