from app.database import session


def test_warehouse_url_falls_back_to_operational_url():
    assert session.WAREHOUSE_DATABASE_URL


def test_warehouse_engine_uses_configured_url():
    assert (
        session.warehouse_engine.url.render_as_string(hide_password=False)
        == session.WAREHOUSE_DATABASE_URL
    )
