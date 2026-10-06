import os
import sys

from dotenv import load_dotenv
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

load_dotenv()

def with_driver(url):
    """Pin plain postgres URLs to psycopg2, the driver in requirements.txt.
    SQLAlchemy 2.1 changed the default for "postgresql://" to psycopg 3."""
    if url and url.startswith(("postgresql://", "postgres://")):
        return "postgresql+psycopg2://" + url.split("://", 1)[1]
    return url


DATABASE_URL = with_driver(os.getenv("DATABASE_URL"))

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is missing from backend/.env"
    )

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)

# Large public datasets and AVM training data can live in a separate,
# self-hosted PostgreSQL database. Falling back to DATABASE_URL preserves the
# original single-database setup for the API and test environments.
WAREHOUSE_DATABASE_URL = with_driver(os.getenv("WAREHOUSE_DATABASE_URL")) or DATABASE_URL
WAREHOUSE_IS_FALLBACK = not os.getenv("WAREHOUSE_DATABASE_URL")
warehouse_engine = create_engine(
    WAREHOUSE_DATABASE_URL,
    pool_pre_ping=True,
)


def _running_pipeline_module() -> bool:
    main_spec = getattr(sys.modules.get("__main__"), "__spec__", None)
    return bool(main_spec and main_spec.name.startswith("pipeline."))


# Pipeline scripts (importers, AVM training) must not silently bulk-load
# warehouse data into the operational Supabase database. Refusing at connect
# time also covers raw_connection()/COPY paths, and leaves pipelines that only
# use the operational engine unaffected.
if (
    WAREHOUSE_IS_FALLBACK
    and _running_pipeline_module()
    and os.getenv("ALLOW_WAREHOUSE_FALLBACK") != "1"
):

    @event.listens_for(warehouse_engine, "do_connect")
    def _refuse_warehouse_fallback(*_args, **_kwargs):
        raise RuntimeError(
            "WAREHOUSE_DATABASE_URL is not set, so this pipeline would write "
            "warehouse data to DATABASE_URL (Supabase). Set "
            "WAREHOUSE_DATABASE_URL, or set ALLOW_WAREHOUSE_FALLBACK=1 to "
            "use the operational database deliberately."
        )

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

WarehouseSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=warehouse_engine,
)


def test_database_connection() -> None:
    print("Testing operational database connection...")

    with engine.connect() as connection:
        result = connection.execute(
            text("SELECT current_database(), NOW()")
        )

        database_name, server_time = result.one()

        print("Connected successfully.")
        print(f"Database: {database_name}")
        print(f"Server time: {server_time}")


def test_warehouse_connection() -> None:
    print("Testing warehouse database connection...")

    with warehouse_engine.connect() as connection:
        database_name, server_time = connection.execute(
            text("SELECT current_database(), NOW()")
        ).one()

        print("Connected successfully.")
        print(f"Database: {database_name}")
        print(f"Server time: {server_time}")


if __name__ == "__main__":
    test_database_connection()
    test_warehouse_connection()
