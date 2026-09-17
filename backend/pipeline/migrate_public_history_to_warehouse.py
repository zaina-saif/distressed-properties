"""Copy public property history from the operational DB to the warehouse DB."""
from __future__ import annotations

import argparse

from sqlalchemy import MetaData, Table, select
from sqlalchemy.dialects.postgresql import insert

from app.database.session import engine, warehouse_engine

TABLES = (
    ("public_data_sources", ("source_id",)),
    ("public_property_snapshots", ("source_id", "source_parcel_id", "snapshot_year")),
    ("public_property_sales", ("source_id", "source_parcel_id", "transaction_id")),
)


def copy_table(table_name: str, conflict_columns: tuple[str, ...], batch_size: int) -> int:
    source_metadata = MetaData()
    target_metadata = MetaData()
    source_table = Table(table_name, source_metadata, autoload_with=engine)
    target_table = Table(table_name, target_metadata, autoload_with=warehouse_engine)
    transferable = [column.name for column in target_table.columns if column.name != "id"]
    total = 0

    with engine.connect() as source, warehouse_engine.begin() as target:
        result = source.execution_options(stream_results=True).execute(
            select(*(source_table.c[name] for name in transferable))
        )
        while rows := result.mappings().fetchmany(batch_size):
            payload = [dict(row) for row in rows]
            statement = insert(target_table).values(payload)
            updates = {
                name: getattr(statement.excluded, name)
                for name in transferable
                if name not in conflict_columns and name not in {"created_at"}
            }
            statement = statement.on_conflict_do_update(
                index_elements=list(conflict_columns), set_=updates
            )
            target.execute(statement)
            total += len(payload)
            print(f"{table_name}: {total:,}")
    return total


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=2_000)
    args = parser.parse_args()
    if engine.url == warehouse_engine.url:
        raise RuntimeError("DATABASE_URL and WAREHOUSE_DATABASE_URL must be different")
    for table_name, conflict_columns in TABLES:
        copy_table(table_name, conflict_columns, args.batch_size)


if __name__ == "__main__":
    main()
