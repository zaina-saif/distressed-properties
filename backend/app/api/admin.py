"""User management for developers: every account with its role and access, and
changes to a user's role or plan. main.py mounts the router behind
require_developer. Every change is written to user_access_changes.

Roles: user (sale data as their plan allows), developer (everything, and this
panel), file_uploader (the private file storage only). A plan set here is a
manual grant (plan_status 'active'); a user with a Stripe subscription keeps
it, and Stripe's next webhook for that subscription sets the plan again.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from app.api.account import check_coverage
from app.auth import Access, require_developer
from app.database.session import engine

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

Role = Literal["user", "developer", "file_uploader"]
GrantedPlan = Literal["none", "free", "starter", "pro"]
ACTIVE = ("active", "trialing", "past_due")


class UserRow(BaseModel):
    user_id: str
    email: str
    name: Optional[str]
    role: Role
    plan: str
    plan_status: str
    coverage_state: Optional[str]
    coverage_county: Optional[str]
    trial_ends_at: Optional[datetime]
    has_subscription: bool
    access_level: str
    created_at: Optional[datetime]
    last_sign_in_at: Optional[datetime]


class AccessChange(BaseModel):
    role: Optional[Role] = None
    plan: Optional[GrantedPlan] = None
    coverage_state: Optional[str] = None
    coverage_county: Optional[str] = None


def access_level(row: dict[str, Any], now: datetime | None = None) -> str:
    """What the account can see, in words: "Developer (admin)", "Full access (Pro)",
    "1 state: NJ (Starter)", "Free: Monmouth County, NJ", "File uploads only", ..."""
    if row["role"] == "developer":
        return "Developer (admin)"
    if row["role"] == "file_uploader":
        return "File uploads only"
    plan, status = row["plan"], row["plan_status"]
    if plan == "trial":
        ends = row.get("trial_ends_at")
        if status == "active" and ends and ends > (now or datetime.now(ends.tzinfo)):
            return f"Trial: full access until {ends:%b %d, %Y}"
        return "No access (trial ended)"
    if plan == "pro" and status in ACTIVE:
        return "Full access (Pro)"
    if plan == "starter" and status in ACTIVE and row.get("coverage_state"):
        return f"1 state: {row['coverage_state']} (Starter)"
    if plan == "free" and status == "active" and row.get("coverage_county"):
        return f"Free: {row['coverage_county']} County, {row['coverage_state']}"
    if plan in ("starter", "pro") and status == "canceled":
        return f"No access ({plan.title()} canceled)"
    return "No access"


def _users(user_id: str | None = None) -> list[dict[str, Any]]:
    # to_jsonb reads Supabase's auth.users columns without naming them, so a stand-in
    # auth.users without them (docker/postgres-init) still works.
    with engine.connect() as connection:
        return [dict(row) for row in connection.execute(text("""
            SELECT a.user_id::text, a.email, a.role, a.plan, a.plan_status, a.coverage_state, a.coverage_county,
                   a.trial_ends_at, a.stripe_subscription_id IS NOT NULL AS has_subscription, a.created_at,
                   NULLIF(COALESCE(to_jsonb(u)->'raw_user_meta_data'->>'full_name',
                                   to_jsonb(u)->'raw_user_meta_data'->>'name'), '') AS name,
                   CAST(to_jsonb(u)->>'last_sign_in_at' AS TIMESTAMPTZ) AS last_sign_in_at
            FROM user_accounts a LEFT JOIN auth.users u ON u.id = a.user_id
            WHERE CAST(:user_id AS uuid) IS NULL OR a.user_id = CAST(:user_id AS uuid)
            ORDER BY (a.role = 'developer') DESC, a.created_at DESC
        """), {"user_id": user_id}).mappings()]


def _user_row(row: dict[str, Any]) -> UserRow:
    return UserRow(**row, access_level=access_level(row))


@router.get("/users", response_model=list[UserRow])
def list_users(access: Access = Depends(require_developer)) -> list[UserRow]:
    return [_user_row(row) for row in _users()]


@router.patch("/users/{user_id}", response_model=UserRow)
def change_access(user_id: str, change: AccessChange, access: Access = Depends(require_developer)) -> UserRow:
    found = _users(user_id)
    if not found:
        raise HTTPException(status_code=404, detail="User not found.")
    current = found[0]
    if user_id == access.user_id and change.role and change.role != "developer":
        raise HTTPException(status_code=400, detail="You cannot remove your own developer role.")
    updates: dict[str, Any] = {}
    if change.role and change.role != current["role"]:
        updates["role"] = change.role
    if change.plan is not None:
        state = county = None
        if change.plan == "starter":
            if not change.coverage_state:
                raise HTTPException(status_code=400, detail="Choose the state for a Starter plan.")
            state, _ = check_coverage(change.coverage_state, None)
        elif change.plan == "free":
            if not (change.coverage_state and change.coverage_county):
                raise HTTPException(status_code=400, detail="Choose the state and county for a Free plan.")
            state, county = check_coverage(change.coverage_state, change.coverage_county)
        updates.update(plan=change.plan, plan_status="inactive" if change.plan == "none" else "active",
                       coverage_state=state, coverage_county=county)
    updates = {key: value for key, value in updates.items() if value != current.get(key)}
    if updates:
        assignments = ", ".join(f"{column} = :{column}" for column in updates)
        with engine.begin() as connection:
            connection.execute(text(f"""UPDATE user_accounts SET {assignments}, updated_at = NOW()
                WHERE user_id = CAST(:user_id AS uuid)"""), {**updates, "user_id": user_id})
            for field, value in updates.items():
                connection.execute(text("""INSERT INTO user_access_changes (user_id, changed_by, field, old_value, new_value)
                    VALUES (CAST(:user_id AS uuid), CAST(:changed_by AS uuid), :field, :old, :new)"""),
                    {"user_id": user_id, "changed_by": access.user_id, "field": field,
                     "old": None if current.get(field) is None else str(current[field]),
                     "new": None if value is None else str(value)})
    return _user_row(_users(user_id)[0])
