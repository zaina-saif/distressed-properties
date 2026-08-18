import asyncio
import json
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from pipeline.adapters.monmouth import MonmouthCivilViewAdapter


def json_serializer(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, Decimal):
        return str(value)

    raise TypeError(
        f"Object of type {type(value).__name__} "
        "is not JSON serializable"
    )


async def main() -> None:
    print(
        "Downloading Monmouth County CivilView listings..."
    )

    adapter = MonmouthCivilViewAdapter()

    # This now downloads the listing and enriches every record
    # from its detail page. Do not run another detail-page loop.
    sale_ids = await adapter.fetch_sale_index()

    all_records: list[dict] = []
    scheduled_records: list[dict] = []

    judgment_count = 0
    upset_count = 0

    for sale_id in sale_ids:
        sale = await adapter.fetch_sale(sale_id)
        record_dict = asdict(sale)

        all_records.append(record_dict)

        if sale.status == "scheduled":
            scheduled_records.append(record_dict)

        if getattr(sale, "judgment_amount", None) is not None:
            judgment_count += 1

        if sale.upset_price is not None:
            upset_count += 1

    all_output = Path(
        "monmouth_all_sheriff_sales.json"
    )

    scheduled_output = Path(
        "monmouth_scheduled_sheriff_sales.json"
    )

    all_output.write_text(
        json.dumps(
            all_records,
            indent=2,
            default=json_serializer,
        ),
        encoding="utf-8",
    )

    scheduled_output.write_text(
        json.dumps(
            scheduled_records,
            indent=2,
            default=json_serializer,
        ),
        encoding="utf-8",
    )

    print()
    print(f"Found {len(all_records)} total sale records.")
    print(f"Scheduled records: {len(scheduled_records)}")
    print(f"Judgment amounts found: {judgment_count}")
    print(f"Upset prices found: {upset_count}")
    print()
    print(f"Saved all records to: {all_output.resolve()}")
    print(
        "Saved scheduled records to: "
        f"{scheduled_output.resolve()}"
    )


if __name__ == "__main__":
    asyncio.run(main())