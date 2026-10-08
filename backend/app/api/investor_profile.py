"""The signed-in user's optional investor profile.

Investors may describe what they are looking for (budget, states, strategy,
timeframe ...) so we can send them matching opportunities. Every field is
optional and no plan is required; email alerts are sent only to users who
opt in, and the time of that consent is recorded.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.api.account import SUPPORTED_STATES
from app.auth import Access, current_user
from app.database.session import engine

router = APIRouter(prefix="/api/v1/account", tags=["investor-profile"])

# Allowed answers; the frontend form offers the same options.
OPTIONS: dict[str, tuple[str, ...]] = {
    "budget_range": ("under_100k", "100k_250k", "250k_500k", "500k_1m", "over_1m"),
    "strategies": ("fix_and_flip", "buy_and_hold", "wholesale", "owner_occupant", "land_development"),
    "property_types": ("single_family", "multi_2_4", "condo_townhouse", "multi_5_plus", "commercial", "land"),
    "timeframe": ("now", "within_3_months", "3_6_months", "6_12_months", "exploring"),
    "financing": ("cash", "hard_money", "conventional", "not_sure"),
    "experience": ("first_purchase", "1_5", "6_20", "20_plus"),
    "min_equity": ("any", "25k", "50k", "100k"),
}
FIELDS = ("budget_range", "states", "strategies", "property_types", "timeframe", "financing", "experience",
          "min_equity", "email_alerts", "alert_frequency", "notes")


class Profile(BaseModel):
    budget_range: Optional[str] = None
    states: list[str] = Field(default_factory=list, max_length=30)
    strategies: list[str] = Field(default_factory=list, max_length=10)
    property_types: list[str] = Field(default_factory=list, max_length=10)
    timeframe: Optional[str] = None
    financing: Optional[str] = None
    experience: Optional[str] = None
    min_equity: Optional[str] = None
    email_alerts: bool = False
    alert_frequency: Optional[Literal["daily", "weekly"]] = None
    notes: Optional[str] = Field(default=None, max_length=1000)


def clean(profile: Profile) -> dict[str, Any]:
    """Validate choices against OPTIONS and drop duplicates; unknown values are rejected."""
    data = profile.model_dump()
    for field, allowed in OPTIONS.items():
        value = data[field]
        values = value if isinstance(value, list) else [value] if value else []
        bad = [item for item in values if item not in allowed]
        if bad:
            raise HTTPException(status_code=400, detail=f"Unknown {field.replace('_', ' ')}: {', '.join(bad)}")
        if isinstance(value, list):
            data[field] = list(dict.fromkeys(value))
    states = [state.strip().upper() for state in data["states"]]
    unknown = [state for state in states if state not in SUPPORTED_STATES]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Not a covered state: {', '.join(unknown)}")
    data["states"] = list(dict.fromkeys(states))
    data["notes"] = (data["notes"] or "").strip() or None
    if data["email_alerts"]:
        data["alert_frequency"] = data["alert_frequency"] or "weekly"
    else:
        data["alert_frequency"] = None
    return data


@router.get("/profile")
def get_profile(access: Access = Depends(current_user)) -> dict[str, Any]:
    with engine.connect() as connection:
        row = connection.execute(text(f"""SELECT {", ".join(FIELDS)}, updated_at FROM investor_profiles
            WHERE user_id = :user_id"""), {"user_id": access.user_id}).mappings().first()
    if row is None:
        return {"exists": False, **Profile().model_dump()}
    return {"exists": True, **dict(row)}


@router.put("/profile")
def save_profile(profile: Profile, access: Access = Depends(current_user)) -> dict[str, Any]:
    data = clean(profile)
    with engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO investor_profiles (user_id, budget_range, states, strategies, property_types, timeframe,
                financing, experience, min_equity, email_alerts, alert_frequency, email_alerts_consented_at, notes)
            VALUES (:user_id, :budget_range, :states, :strategies, :property_types, :timeframe, :financing,
                :experience, :min_equity, :email_alerts, :alert_frequency,
                CASE WHEN :email_alerts THEN NOW() END, :notes)
            ON CONFLICT (user_id) DO UPDATE SET
                budget_range = EXCLUDED.budget_range, states = EXCLUDED.states, strategies = EXCLUDED.strategies,
                property_types = EXCLUDED.property_types, timeframe = EXCLUDED.timeframe,
                financing = EXCLUDED.financing, experience = EXCLUDED.experience, min_equity = EXCLUDED.min_equity,
                email_alerts = EXCLUDED.email_alerts, alert_frequency = EXCLUDED.alert_frequency,
                -- Keep the original consent time while alerts stay on; clear it when they are turned off.
                email_alerts_consented_at = CASE WHEN EXCLUDED.email_alerts
                    THEN COALESCE(investor_profiles.email_alerts_consented_at, NOW()) END,
                notes = EXCLUDED.notes, updated_at = NOW()
        """), {"user_id": access.user_id, **data})
    return {"exists": True, **data}
