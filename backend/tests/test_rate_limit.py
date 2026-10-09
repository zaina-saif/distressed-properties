from fastapi.testclient import TestClient

import app.rate_limit as rate_limit
from app.auth import Access, current_user
from app.main import app


def test_window_allows_up_to_the_limit_then_waits():
    rate_limit._hits.clear()
    assert all(rate_limit.check("b", "u", 3, 60, now=100 + i) is None for i in range(3))
    wait = rate_limit.check("b", "u", 3, 60, now=110)
    assert wait == 50  # the first hit at 100 expires at 160
    assert rate_limit.check("b", "other", 3, 60, now=110) is None
    assert rate_limit.check("b", "u", 3, 60, now=161) is None


def test_export_returns_429_with_retry_after(monkeypatch):
    rate_limit._hits.clear()
    app.dependency_overrides[current_user] = lambda: Access("user-1", "a@example.com", plan="pro", plan_status="active")
    try:
        for _ in range(20):
            rate_limit.check("export", "user-1", 20, 3600)
        response = TestClient(app).get("/api/v1/properties/export.xlsx")
        assert response.status_code == 429 and int(response.headers["Retry-After"]) > 0
    finally:
        app.dependency_overrides.clear()


def test_developers_are_not_limited():
    rate_limit._hits.clear()
    dependency = rate_limit.per_user("x", 1)
    developer = Access("dev", "d@example.com", role="developer")
    assert dependency(developer) is developer and dependency(developer) is developer
