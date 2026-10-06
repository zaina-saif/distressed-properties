from app.database.session import with_driver


def test_plain_postgres_urls_use_psycopg2():
    assert with_driver("postgresql://u:p@h:5432/db") == "postgresql+psycopg2://u:p@h:5432/db"
    assert with_driver("postgres://u:p@h/db") == "postgresql+psycopg2://u:p@h/db"


def test_explicit_drivers_are_kept():
    assert with_driver("postgresql+psycopg2://u@h/db") == "postgresql+psycopg2://u@h/db"
    assert with_driver(None) is None
