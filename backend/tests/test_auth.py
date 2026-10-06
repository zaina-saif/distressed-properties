import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app.auth as auth
from app.api import account
from app.auth import Access, current_user
from app.main import app

URL = "https://project.supabase.co"
PRIVATE_KEY = ec.generate_private_key(ec.SECP256R1())


class FakeJwks:
    def get_signing_key_from_jwt(self, token):
        return type("Key", (), {"key": PRIVATE_KEY.public_key()})()


@pytest.fixture
def signing(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", URL)
    monkeypatch.setattr(auth, "_jwks_client", lambda url: FakeJwks())
    # Without a publishable key the Auth-server fallback refuses instead of calling out.
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_PUBLISHABLE_KEY", raising=False)
    auth._confirmed.clear()


def token(**claims):
    payload = {"sub": "user-1", "email": "a@example.com", "aud": "authenticated", "iss": f"{URL}/auth/v1",
               "exp": int(time.time()) + 600, **claims}
    return jwt.encode(payload, PRIVATE_KEY, algorithm="ES256")


def test_valid_token_is_accepted(signing):
    assert auth.verify_token(token())["sub"] == "user-1"


@pytest.mark.parametrize("claims", [{"aud": "anon"}, {"iss": "https://other.supabase.co/auth/v1"},
                                    {"exp": int(time.time()) - 10}])
def test_bad_tokens_are_rejected(signing, claims):
    with pytest.raises(HTTPException) as error:
        auth.verify_token(token(**claims))
    assert error.value.status_code == 401


def test_token_signed_by_another_key_is_rejected(signing):
    forged = jwt.encode({"sub": "x", "aud": "authenticated", "iss": f"{URL}/auth/v1", "exp": int(time.time()) + 60},
                        ec.generate_private_key(ec.SECP256R1()), algorithm="ES256")
    with pytest.raises(HTTPException):
        auth.verify_token(forged)


def test_legacy_token_is_confirmed_by_the_auth_server(signing, monkeypatch):
    legacy = jwt.encode({"sub": "user-9", "aud": "authenticated", "exp": int(time.time()) + 600},
                        "legacy-shared-secret-for-tests-0123456789", algorithm="HS256")
    calls = []

    def fake_get(url, headers, timeout):
        calls.append((url, headers["apikey"], headers["Authorization"]))
        return type("Response", (), {"status_code": 200, "json": lambda self: {"id": "user-9", "email": "l@example.com"}})()

    monkeypatch.setenv("SUPABASE_ANON_KEY", "sb_publishable_x")
    monkeypatch.setattr(auth.httpx, "get", fake_get)
    assert auth.verify_token(legacy) == {"sub": "user-9", "email": "l@example.com"}
    assert auth.verify_token(legacy)["sub"] == "user-9"  # second call is served from the cache
    assert calls == [(f"{URL}/auth/v1/user", "sb_publishable_x", f"Bearer {legacy}")]


def test_auth_server_rejection_is_unauthorized(signing, monkeypatch):
    legacy = jwt.encode({"sub": "x", "exp": int(time.time()) + 600}, "another-legacy-secret-for-tests-012345", algorithm="HS256")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "sb_publishable_x")
    monkeypatch.setattr(auth.httpx, "get", lambda *a, **k: type("R", (), {"status_code": 401})())
    with pytest.raises(HTTPException) as error:
        auth.verify_token(legacy)
    assert error.value.status_code == 401


def test_plan_rules():
    free = Access("u", "e", plan="free", plan_status="active", coverage_state="nj", coverage_county="Essex")
    assert free.has_plan and free.scope_state == "NJ" and free.scope_county == "Essex"
    assert free.covers("NJ", "essex") and not free.covers("NJ", "Bergen") and not free.covers("PA", "Essex")
    starter = Access("u", "e", plan="starter", plan_status="active", coverage_state="OH")
    assert starter.covers("OH", "Cuyahoga") and not starter.covers("FL", "Lee")
    pro = Access("u", "e", plan="pro", plan_status="active")
    assert pro.has_plan and pro.scope_state is None and pro.covers("FL", "Lee")
    assert not Access("u", "e", plan="pro", plan_status="past_due").has_plan
    assert not Access("u", "e", plan="starter", plan_status="active").has_plan  # no state chosen yet
    assert not Access("u", "e").has_plan
    developer = Access("u", "e", role="developer")
    assert developer.has_plan and developer.scope_state is None and developer.is_developer


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


def signed_in_as(access):
    app.dependency_overrides[current_user] = lambda: access


def test_data_routes_need_sign_in(client):
    for path in ("/api/v1/properties", "/api/v1/properties/export.xlsx", "/api/v1/properties/abc",
                 "/api/v1/properties/abc/street-view", "/api/v1/properties/abc/liens", "/api/v1/sale-pages/abc",
                 "/api/v1/pa/imports/status", "/api/v1/account/me"):
        assert client.get(path).status_code == 401, path


def test_data_routes_need_a_plan(client):
    signed_in_as(Access("u", "e"))
    assert client.get("/api/v1/properties").status_code == 402
    assert client.get("/api/v1/properties/abc/liens").status_code == 402


def test_developer_routes_refuse_subscribers(client):
    signed_in_as(Access("u", "e", plan="pro", plan_status="active"))
    assert client.get("/api/v1/pa/imports/status").status_code == 403
    assert client.get("/api/v1/lien-jobs/abc").status_code == 403
    assert client.post("/api/v1/properties/abc/liens/refresh").status_code == 403
    assert client.get("/api/v1/properties/parcel-review/candidates").status_code == 403


def test_webhook_rejects_unsigned_events(client, monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    response = client.post("/api/v1/billing/webhook", content=b"{}", headers={"Stripe-Signature": "t=1,v1=bad"})
    assert response.status_code == 400


def test_prices_map_to_plans(monkeypatch):
    monkeypatch.setenv("STRIPE_PRICE_STARTER_MONTH", "price_s_m")
    monkeypatch.setenv("STRIPE_PRICE_PRO_YEAR", "price_p_y")
    assert account.plan_for_price("price_p_y") == ("pro", "year")
    assert account.plan_for_price("price_other") is None
    assert account._period_end({"items": {"data": [{"current_period_end": 1_800_000_000}]}}).year == 2027
