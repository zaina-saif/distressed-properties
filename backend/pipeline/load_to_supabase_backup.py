import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.database.session import engine


JSON_FILE = Path("monmouth_all_sheriff_sales.json")


def calculate_hash(data: dict[str, Any]) -> str:
    serialized = json.dumps(
        data,
        sort_keys=True,
        default=str,
    )

    return hashlib.sha256(
        serialized.encode("utf-8")
    ).hexdigest()


def load_records() -> list[dict[str, Any]]:
    if not JSON_FILE.exists():
        raise FileNotFoundError(
            f"{JSON_FILE} was not found. "
            "Run the CivilView scraper first."
        )

    records = json.loads(
        JSON_FILE.read_text(encoding="utf-8")
    )

    if not isinstance(records, list):
        raise ValueError(
            "The CivilView JSON file must contain a list."
        )

    return records


def load_into_supabase() -> None:
    records = load_records()

    scrape_run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)

    created_count = 0
    updated_count = 0
    failed_count = 0

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO scrape_runs (
                    id,
                    job_name,
                    county,
                    source_system,
                    started_at,
                    status,
                    records_found
                )
                VALUES (
                    :id,
                    :job_name,
                    :county,
                    :source_system,
                    :started_at,
                    :status,
                    :records_found
                )
                """
            ),
            {
                "id": scrape_run_id,
                "job_name": "monmouth_civilview_scrape",
                "county": "Monmouth",
                "source_system": "civilview",
                "started_at": started_at,
                "status": "running",
                "records_found": len(records),
            },
        )

        for record in records:
            try:
                sheriff_number = record["sheriff_number"]
                status = record.get("status", "unknown")
                sale_date = record.get("sale_date")

                source_url = record.get(
                    "source_url",
                    "https://salesweb.civilview.com/",
                )

                raw_payload = record.get(
                    "raw_payload",
                    {},
                )

                if not isinstance(raw_payload, dict):
                    raw_payload = {}

                raw_status = raw_payload.get(
                    "raw_status",
                    status,
                )

                plaintiff = (
                    record.get("plaintiff")
                    or raw_payload.get("plaintiff")
                )

                defendant = (
                    record.get("defendant")
                    or raw_payload.get("defendant")
                )

                address = (
                    record.get("address")
                    or raw_payload.get("address")
                )

                court_case_number = record.get(
                    "court_case_number"
                )

                plaintiff_attorney = record.get(
                    "plaintiff_attorney"
                )

                judgment_amount = record.get(
                    "judgment_amount"
                )

                upset_price = record.get(
                    "upset_price"
                )

                content_hash = calculate_hash(record)
                scraped_at = datetime.now(timezone.utc)

                existing_sale = connection.execute(
                    text(
                        """
                        SELECT
                            id,
                            current_status,
                            current_sale_date
                        FROM sheriff_sales
                        WHERE county = :county
                          AND sheriff_number = :sheriff_number
                        """
                    ),
                    {
                        "county": "Monmouth",
                        "sheriff_number": sheriff_number,
                    },
                ).mappings().first()

                connection.execute(
                    text(
                        """
                        INSERT INTO raw_scrape_records (
                            id,
                            scrape_run_id,
                            county,
                            source_record_id,
                            source_url,
                            raw_payload,
                            content_hash,
                            parsing_status,
                            scraped_at
                        )
                        VALUES (
                            :id,
                            :scrape_run_id,
                            :county,
                            :source_record_id,
                            :source_url,
                            CAST(:raw_payload AS JSONB),
                            :content_hash,
                            :parsing_status,
                            :scraped_at
                        )
                        ON CONFLICT (
                            county,
                            source_record_id,
                            content_hash
                        )
                        DO NOTHING
                        """
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "scrape_run_id": scrape_run_id,
                        "county": "Monmouth",
                        "source_record_id": sheriff_number,
                        "source_url": source_url,
                        "raw_payload": json.dumps(record),
                        "content_hash": content_hash,
                        "parsing_status": "parsed",
                        "scraped_at": scraped_at,
                    },
                )

                if existing_sale is None:
                    sheriff_sale_id = str(uuid.uuid4())

                    connection.execute(
                        text(
                            """
                            INSERT INTO sheriff_sales (
                                id,
                                county,
                                sheriff_number,
                                court_case_number,
                                plaintiff,
                                defendant,
                                plaintiff_attorney,
                                current_sale_date,
                                current_status,
                                judgment_amount,
                                upset_price,
                                source_url,
                                source_system,
                                first_seen_at,
                                last_seen_at,
                                last_scraped_at,
                                raw_source_hash,
                                is_active
                            )
                            VALUES (
                                :id,
                                :county,
                                :sheriff_number,
                                :court_case_number,
                                :plaintiff,
                                :defendant,
                                :plaintiff_attorney,
                                :current_sale_date,
                                :current_status,
                                :judgment_amount,
                                :upset_price,
                                :source_url,
                                :source_system,
                                :first_seen_at,
                                :last_seen_at,
                                :last_scraped_at,
                                :raw_source_hash,
                                TRUE
                            )
                            """
                        ),
                        {
                            "id": sheriff_sale_id,
                            "county": "Monmouth",
                            "sheriff_number": sheriff_number,
                            "court_case_number": (
                                court_case_number
                            ),
                            "plaintiff": plaintiff,
                            "defendant": defendant,
                            "plaintiff_attorney": (
                                plaintiff_attorney
                            ),
                            "current_sale_date": sale_date,
                            "current_status": status,
                            "judgment_amount": (
                                judgment_amount
                            ),
                            "upset_price": upset_price,
                            "source_url": source_url,
                            "source_system": "civilview",
                            "first_seen_at": scraped_at,
                            "last_seen_at": scraped_at,
                            "last_scraped_at": scraped_at,
                            "raw_source_hash": content_hash,
                        },
                    )

                    connection.execute(
                        text(
                            """
                            INSERT INTO sheriff_sale_status_history (
                                id,
                                sheriff_sale_id,
                                status,
                                sale_date,
                                upset_price,
                                observed_at,
                                source_url,
                                raw_status
                            )
                            VALUES (
                                :id,
                                :sheriff_sale_id,
                                :status,
                                :sale_date,
                                :upset_price,
                                :observed_at,
                                :source_url,
                                :raw_status
                            )
                            """
                        ),
                        {
                            "id": str(uuid.uuid4()),
                            "sheriff_sale_id": sheriff_sale_id,
                            "status": status,
                            "sale_date": sale_date,
                            "upset_price": upset_price,
                            "observed_at": scraped_at,
                            "source_url": source_url,
                            "raw_status": raw_status,
                        },
                    )

                    created_count += 1

                else:
                    sheriff_sale_id = str(
                        existing_sale["id"]
                    )

                    previous_status = (
                        existing_sale["current_status"]
                    )

                    previous_sale_date = (
                        existing_sale["current_sale_date"]
                    )

                    connection.execute(
                        text(
                            """
                            UPDATE sheriff_sales
                            SET
                                court_case_number = COALESCE(
                                    :court_case_number,
                                    court_case_number
                                ),
                                plaintiff = COALESCE(
                                    :plaintiff,
                                    plaintiff
                                ),
                                defendant = COALESCE(
                                    :defendant,
                                    defendant
                                ),
                                plaintiff_attorney = COALESCE(
                                    :plaintiff_attorney,
                                    plaintiff_attorney
                                ),
                                current_sale_date =
                                    :current_sale_date,
                                current_status =
                                    :current_status,
                                judgment_amount = COALESCE(
                                    :judgment_amount,
                                    judgment_amount
                                ),
                                upset_price = COALESCE(
                                    :upset_price,
                                    upset_price
                                ),
                                source_url = :source_url,
                                last_seen_at = :last_seen_at,
                                last_scraped_at =
                                    :last_scraped_at,
                                raw_source_hash =
                                    :raw_source_hash,
                                is_active = TRUE,
                                updated_at = NOW()
                            WHERE id = :id
                            """
                        ),
                        {
                            "id": sheriff_sale_id,
                            "court_case_number": (
                                court_case_number
                            ),
                            "plaintiff": plaintiff,
                            "defendant": defendant,
                            "plaintiff_attorney": (
                                plaintiff_attorney
                            ),
                            "current_sale_date": sale_date,
                            "current_status": status,
                            "judgment_amount": (
                                judgment_amount
                            ),
                            "upset_price": upset_price,
                            "source_url": source_url,
                            "last_seen_at": scraped_at,
                            "last_scraped_at": scraped_at,
                            "raw_source_hash": content_hash,
                        },
                    )

                    status_changed = (
                        previous_status != status
                    )

                    sale_date_changed = (
                        str(previous_sale_date)
                        != str(sale_date)
                    )

                    if status_changed or sale_date_changed:
                        connection.execute(
                            text(
                                """
                                INSERT INTO
                                    sheriff_sale_status_history (
                                        id,
                                        sheriff_sale_id,
                                        status,
                                        sale_date,
                                        upset_price,
                                        observed_at,
                                        source_url,
                                        raw_status
                                    )
                                VALUES (
                                    :id,
                                    :sheriff_sale_id,
                                    :status,
                                    :sale_date,
                                    :upset_price,
                                    :observed_at,
                                    :source_url,
                                    :raw_status
                                )
                                """
                            ),
                            {
                                "id": str(uuid.uuid4()),
                                "sheriff_sale_id": (
                                    sheriff_sale_id
                                ),
                                "status": status,
                                "sale_date": sale_date,
                                "upset_price": upset_price,
                                "observed_at": scraped_at,
                                "source_url": source_url,
                                "raw_status": raw_status,
                            },
                        )

                    updated_count += 1

                print(
                    f"Saved {sheriff_number} | "
                    f"{status} | "
                    f"{address or 'address unavailable'}"
                )

            except Exception as exc:
                failed_count += 1

                print(
                    f"Failed to save "
                    f"{record.get('sheriff_number')}: "
                    f"{type(exc).__name__}: {exc}"
                )

        final_status = (
            "completed"
            if failed_count == 0
            else "partially_completed"
        )

        connection.execute(
            text(
                """
                UPDATE scrape_runs
                SET
                    completed_at = :completed_at,
                    status = :status,
                    records_created = :records_created,
                    records_updated = :records_updated,
                    records_failed = :records_failed
                WHERE id = :id
                """
            ),
            {
                "id": scrape_run_id,
                "completed_at": datetime.now(
                    timezone.utc
                ),
                "status": final_status,
                "records_created": created_count,
                "records_updated": updated_count,
                "records_failed": failed_count,
            },
        )

    print()
    print("Supabase import complete.")
    print(f"Created: {created_count}")
    print(f"Updated: {updated_count}")
    print(f"Failed: {failed_count}")


if __name__ == "__main__":
    load_into_supabase()