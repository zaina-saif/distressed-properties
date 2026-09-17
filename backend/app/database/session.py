import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

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
# original single-database setup for existing deployments and test environments.
WAREHOUSE_DATABASE_URL = os.getenv("WAREHOUSE_DATABASE_URL", DATABASE_URL)
warehouse_engine = create_engine(
    WAREHOUSE_DATABASE_URL,
    pool_pre_ping=True,
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
