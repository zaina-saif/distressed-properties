"""Batch preliminary lien screening from saved public sheriff-sale notices."""

from __future__ import annotations

import argparse
from collections import Counter

from sqlalchemy import text

from app.api.liens import refresh_liens
from app.database.session import engine


def screen_properties(limit: int | None = None) -> dict:
    limit_clause = "LIMIT :limit" if limit is not None else ""
    with engine.connect() as connection:
        property_ids = list(connection.execute(text(f"""
            SELECT DISTINCT ON (ss.property_id) ss.property_id::text
            FROM sheriff_sales ss
            WHERE ss.property_id IS NOT NULL
              AND ss.description_text IS NOT NULL
              AND btrim(ss.description_text) <> ''
            ORDER BY ss.property_id, ss.current_sale_date DESC NULLS LAST
            {limit_clause}
        """), {"limit": limit} if limit is not None else {}).scalars())

    levels: Counter[str] = Counter()
    records_found = 0
    failures: list[dict[str, str]] = []

    for property_id in property_ids:
        try:
            result = refresh_liens(property_id)
            records_found += result["records_found"]
            levels[result["risk_level"]] += 1
        except Exception as exc:  # batch must continue and report each failure
            failures.append({
                "property_id": property_id,
                "error": str(exc),
            })

    return {
        "screenable": len(property_ids),
        "screened": len(property_ids) - len(failures),
        "failed": len(failures),
        "records_found": records_found,
        "risk_levels": dict(levels),
        "failures": failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    result = screen_properties(args.limit)

    print(f"Screenable properties: {result['screenable']}")
    print(f"Screened successfully: {result['screened']}")
    print(f"Failed: {result['failed']}")
    print(f"Lien/risk records found: {result['records_found']}")
    print(f"Risk levels: {result['risk_levels']}")
    if result["failures"]:
        print("Failures:")
        for failure in result["failures"]:
            print(f"- {failure['property_id']}: {failure['error']}")


if __name__ == "__main__":
    main()
