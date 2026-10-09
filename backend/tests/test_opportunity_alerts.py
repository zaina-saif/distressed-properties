from datetime import date

from fastapi.testclient import TestClient

import app.api.alerts as alerts
from app.main import app
from pipeline.send_opportunity_alerts import criteria, render

PROFILE = {"user_id": "11111111-1111-1111-1111-111111111111", "email": "inv@example.com", "role": "user", "plan": "starter",
           "plan_status": "active", "coverage_state": "NJ", "coverage_county": None, "budget_range": "100k_250k",
           "states": ["NJ", "PA"], "property_types": ["single_family", "commercial"], "min_equity": "50k"}


def test_criteria_apply_plan_coverage_and_profile():
    where, params = criteria(PROFILE)
    assert params["scope_state"] == "NJ"  # Starter covers NJ only, even though the profile also lists PA
    assert params["states"] == ["NJ", "PA"]
    assert (params["budget_low"], params["budget_high"]) == (100_000, 250_000)
    assert params["min_equity"] == 50_000
    assert params["home_types"] == ["MANUFACTURED", "SINGLE_FAMILY"]  # commercial has no Zillow home type
    assert "opportunity_alert_items" in where and "CURRENT_DATE" in where


def test_free_plan_is_limited_to_its_county_and_empty_profile_matches_broadly():
    where, params = criteria({**PROFILE, "plan": "free", "coverage_county": "Essex", "budget_range": None,
                              "states": [], "property_types": [], "min_equity": "any"})
    assert params["scope_county"] == "essex"
    assert not {"budget_low", "budget_high", "min_equity", "home_types", "states"} & set(params)


def test_email_has_unsubscribe_postal_address_and_disclaimer(monkeypatch):
    monkeypatch.setenv("ALERTS_SIGNING_SECRET", "secret")
    sale = {"sale_id": "s1", "street_address": "12 Main St", "city": "Newark", "state": "NJ", "county": "Essex",
            "current_sale_date": date(2026, 11, 3), "zestimate": 300000, "minimum_bid": 180000, "gross_equity": 120000}
    subject, html, text_body = render(PROFILE, [sale], "123 Example Ave, Newark, NJ 07102")
    assert subject == "1 new sale matching your investor profile"
    for body in (html, text_body):
        assert "/api/v1/alerts/unsubscribe?u=" + PROFILE["user_id"] in body
        assert "123 Example Ave, Newark, NJ 07102" in body
        assert "$120,000" in body
        assert "not guaranteed" in body.lower()


def test_unsubscribe_link_must_be_signed(monkeypatch):
    monkeypatch.setenv("ALERTS_SIGNING_SECRET", "secret")
    calls = []

    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def execute(self, statement, params): calls.append(params)

    monkeypatch.setattr(alerts, "engine", type("E", (), {"begin": staticmethod(lambda: Connection())})())
    client = TestClient(app)
    user = PROFILE["user_id"]
    assert client.get(f"/api/v1/alerts/unsubscribe?u={user}&t=forged").status_code == 400
    assert calls == []
    good = client.get(f"/api/v1/alerts/unsubscribe?u={user}&t={alerts.signature(user)}")
    assert good.status_code == 200 and "unsubscribed" in good.text
    assert client.post(f"/api/v1/alerts/unsubscribe?u={user}&t={alerts.signature(user)}").json() == {"unsubscribed": True}
    assert calls == [{"user_id": user}, {"user_id": user}]
