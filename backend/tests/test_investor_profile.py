import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.investor_profile import Profile, clean
from app.main import app


def test_valid_profile_is_normalised():
    data = clean(Profile(budget_range="100k_250k", states=["nj", "PA", "NJ"], strategies=["fix_and_flip", "fix_and_flip"],
                         timeframe="now", email_alerts=True, notes="  Brick ranch homes  "))
    assert data["states"] == ["NJ", "PA"]
    assert data["strategies"] == ["fix_and_flip"]
    assert data["alert_frequency"] == "weekly"  # opted in without choosing a frequency
    assert data["notes"] == "Brick ranch homes"


def test_alert_frequency_is_cleared_without_consent():
    assert clean(Profile(email_alerts=False, alert_frequency="daily"))["alert_frequency"] is None


def test_everything_is_optional():
    data = clean(Profile())
    assert data["states"] == [] and data["budget_range"] is None and data["email_alerts"] is False


@pytest.mark.parametrize("profile", [Profile(budget_range="a lot"), Profile(states=["ZZ"]),
                                     Profile(strategies=["flip_and_fix"]), Profile(min_equity="1m")])
def test_unknown_values_are_rejected(profile):
    with pytest.raises(HTTPException) as error:
        clean(profile)
    assert error.value.status_code == 400


def test_profile_needs_sign_in():
    client = TestClient(app)
    assert client.get("/api/v1/account/profile").status_code == 401
    assert client.put("/api/v1/account/profile", json={}).status_code == 401
