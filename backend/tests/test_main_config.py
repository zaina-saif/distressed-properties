import importlib

from fastapi.testclient import TestClient


def _app(monkeypatch, **env):
    for key in ("CORS_ALLOWED_ORIGINS", "CORS_ALLOWED_ORIGIN_REGEX", "ENABLE_WAREHOUSE_API"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    import app.main
    return importlib.reload(app.main).app


def _preflight(client, origin):
    return client.options("/health", headers={"Origin": origin, "Access-Control-Request-Method": "GET"})


def test_localhost_is_allowed_by_default(monkeypatch):
    client = TestClient(_app(monkeypatch))
    assert _preflight(client, "http://localhost:3000").headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_production_origins_and_preview_regex(monkeypatch):
    client = TestClient(_app(monkeypatch, CORS_ALLOWED_ORIGINS="https://example.com/, https://www.example.com",
                             CORS_ALLOWED_ORIGIN_REGEX=r"https://.*-team\.vercel\.app"))
    assert _preflight(client, "https://example.com").headers.get("access-control-allow-origin") == "https://example.com"
    assert _preflight(client, "https://web-abc-team.vercel.app").headers.get("access-control-allow-origin")
    assert _preflight(client, "http://localhost:3000").headers.get("access-control-allow-origin") is None


def test_warehouse_routes_can_be_disabled(monkeypatch):
    paths = _app(monkeypatch, ENABLE_WAREHOUSE_API="0").openapi()["paths"]
    assert not any(path.startswith("/api/v1/warehouse-valuations") for path in paths)
    paths = _app(monkeypatch).openapi()["paths"]
    assert any(path.startswith("/api/v1/warehouse-valuations") for path in paths)
