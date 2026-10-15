from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import app.api.admin as admin
from app.api.admin import access_level
from app.auth import Access, current_user
from app.main import app

NOW = datetime(2026, 10, 15, tzinfo=timezone.utc)


def row(**values):
    return {"role": "user", "plan": "none", "plan_status": "inactive", "coverage_state": None,
            "coverage_county": None, "trial_ends_at": None, **values}


def test_access_levels_in_words():
    assert access_level(row(role="developer")) == "Developer (admin)"
    assert access_level(row(role="file_uploader", plan="pro", plan_status="active")) == "File uploads only"
    assert access_level(row(plan="pro", plan_status="active")) == "Full access (Pro)"
    assert access_level(row(plan="starter", plan_status="active", coverage_state="NJ")) == "1 state: NJ (Starter)"
    assert access_level(row(plan="free", plan_status="active", coverage_state="NJ", coverage_county="Monmouth")) == \
        "Free: Monmouth County, NJ"
    assert access_level(row(plan="trial", plan_status="active", trial_ends_at=NOW + timedelta(days=3)), NOW) == \
        "Trial: full access until Oct 18, 2026"
    assert access_level(row(plan="trial", plan_status="active", trial_ends_at=NOW - timedelta(days=1)), NOW) == \
        "No access (trial ended)"
    assert access_level(row(plan="pro", plan_status="canceled")) == "No access (Pro canceled)"
    assert access_level(row()) == "No access"


def test_file_uploaders_get_file_storage_and_no_sale_data():
    uploader = Access(user_id="u", email="u@example.com", role="file_uploader", plan="pro", plan_status="active")
    assert uploader.can_upload_files and not uploader.has_plan and not uploader.is_developer
    assert not Access(user_id="u", email="u@example.com", plan="pro", plan_status="active").can_upload_files


def as_user(role):
    app.dependency_overrides[current_user] = lambda: Access(user_id="00000000-0000-0000-0000-000000000001",
                                                            email="dev@example.com", role=role)


def test_user_management_is_developer_only():
    for role in ("user", "file_uploader"):
        as_user(role)
        try:
            client = TestClient(app)
            assert client.get("/api/v1/admin/users").status_code == 403
            assert client.patch("/api/v1/admin/users/x", json={"role": "developer"}).status_code == 403
            assert client.get("/api/v1/admin/changes").status_code == 403
        finally:
            app.dependency_overrides.clear()


def test_a_developer_cannot_remove_their_own_developer_role(monkeypatch):
    me = "00000000-0000-0000-0000-000000000001"
    monkeypatch.setattr(admin, "_users", lambda user_id=None: [row(user_id=me, email="dev@example.com", role="developer")])
    as_user("developer")
    try:
        response = TestClient(app).patch(f"/api/v1/admin/users/{me}", json={"role": "user"})
        assert response.status_code == 400
    finally:
        app.dependency_overrides.clear()


def test_a_state_plan_needs_its_state(monkeypatch):
    other = "00000000-0000-0000-0000-000000000002"
    monkeypatch.setattr(admin, "_users", lambda user_id=None: [row(user_id=other, email="u@example.com")])
    as_user("developer")
    try:
        client = TestClient(app)
        assert client.patch(f"/api/v1/admin/users/{other}", json={"plan": "starter"}).status_code == 400
        assert client.patch(f"/api/v1/admin/users/{other}", json={"plan": "free", "coverage_state": "NJ"}).status_code == 400
        assert client.patch(f"/api/v1/admin/users/{other}", json={"role": "owner"}).status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_file_uploaders_cannot_take_a_plan():
    as_user("file_uploader")
    try:
        client = TestClient(app)
        assert client.post("/api/v1/account/free-plan", json={"state": "NJ", "county": "Monmouth"}).status_code == 403
        assert client.post("/api/v1/billing/checkout", json={"plan": "pro", "interval": "month"}).status_code == 403
    finally:
        app.dependency_overrides.clear()
