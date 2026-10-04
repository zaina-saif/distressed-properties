from app.database import session


def test_warehouse_url_falls_back_to_operational_url():
    assert session.WAREHOUSE_DATABASE_URL


def test_warehouse_engine_uses_configured_url():
    assert (
        session.warehouse_engine.url.render_as_string(hide_password=False)
        == session.WAREHOUSE_DATABASE_URL
    )


def _reload_session(monkeypatch, main_module_name, **env):
    import importlib
    import sys
    import types

    import dotenv
    import pytest

    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.delenv("WAREHOUSE_DATABASE_URL", raising=False)
    monkeypatch.delenv("ALLOW_WAREHOUSE_FALLBACK", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    fake_main = types.ModuleType("__main__")
    fake_main.__spec__ = types.SimpleNamespace(name=main_module_name)
    monkeypatch.setitem(sys.modules, "__main__", fake_main)
    return importlib.reload(session), pytest


def _restore_session():
    import importlib

    importlib.reload(session)


def test_pipeline_refuses_warehouse_fallback(monkeypatch):
    try:
        reloaded, pytest = _reload_session(monkeypatch, "pipeline.import_x")
        assert reloaded.WAREHOUSE_IS_FALLBACK
        with pytest.raises(RuntimeError, match="WAREHOUSE_DATABASE_URL"):
            reloaded.warehouse_engine.connect()
        reloaded.engine.connect().close()
    finally:
        monkeypatch.undo()
        _restore_session()


def test_pipeline_fallback_allowed_when_opted_in(monkeypatch):
    try:
        reloaded, _ = _reload_session(
            monkeypatch, "pipeline.import_x", ALLOW_WAREHOUSE_FALLBACK="1"
        )
        reloaded.warehouse_engine.connect().close()
    finally:
        monkeypatch.undo()
        _restore_session()


def test_api_keeps_warehouse_fallback(monkeypatch):
    try:
        reloaded, _ = _reload_session(monkeypatch, "uvicorn")
        reloaded.warehouse_engine.connect().close()
    finally:
        monkeypatch.undo()
        _restore_session()
