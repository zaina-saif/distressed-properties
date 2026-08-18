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

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


def test_database_connection() -> None:
    print("Testing Supabase database connection...")

    with engine.connect() as connection:
        result = connection.execute(
            text("SELECT current_database(), NOW()")
        )

        database_name, server_time = result.one()

        print("Connected successfully.")
        print(f"Database: {database_name}")
        print(f"Server time: {server_time}")


if __name__ == "__main__":
    test_database_connection()