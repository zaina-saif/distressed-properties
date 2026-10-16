"""Mark timeshare listings as not valued.

    python -m pipeline.flag_timeshares --dry-run
    python -m pipeline.flag_timeshares

A timeshare sale is of a share of a resort unit with yearly use (Atlantic County's
"Fairway Lane, Timeshare Estate No. 32", Wyndham's Skyline Tower at 100 S. North
Carolina Avenue), not a whole home, so a Zestimate or assessed value for the unit or
building says nothing about it and the equity it gives is wrong. A property whose
address or sale notice says it is a timeshare gets properties.valuation_excluded_reason
(migration 044): the Zillow and NYC DOF stages skip it, its current Zillow results and
valuations stop being current (kept as history), and the dashboard shows "Not valued".
Both refreshes run it after loading. A reason already set is left as it is.
"""
from __future__ import annotations

import argparse
import json

from sqlalchemy import text

from app.database.session import engine

REASON = "Timeshare interest: a share of a resort or hotel unit with yearly use, not a whole home; not valued"
# "TIMESHARE ESTATE NO. 32", "TIME SHARE", "OCCUPANCY STATUS: ... IS A TIMESHARE VACATION PROPERTY";
# a notice saying a property is "not a timeshare" is not one.
TIMESHARE = r"time\s*-?\s*share"
NOT_TIMESHARE = r"not\s+(?:a\s+)?time\s*-?\s*share"


def flag(dry_run: bool = False) -> dict[str, int]:
    with engine.begin() as connection:
        ids = [row[0] for row in connection.execute(text("""
            SELECT DISTINCT p.id FROM properties p JOIN sheriff_sales ss ON ss.property_id = p.id
            WHERE p.valuation_excluded_reason IS NULL
              AND (p.street_address ~* :yes OR (ss.description_text ~* :yes AND ss.description_text !~* :no))"""),
            {"yes": TIMESHARE, "no": NOT_TIMESHARE})]
        counts = {"flagged": len(ids), "zillow_results_retired": 0, "valuations_retired": 0}
        if dry_run or not ids:
            return counts
        connection.execute(text("UPDATE properties SET valuation_excluded_reason = :reason, updated_at = NOW() "
                                "WHERE id = ANY(:ids)"), {"reason": REASON, "ids": ids})
        counts["zillow_results_retired"] = connection.execute(text(
            "UPDATE apify_zillow_results SET is_current = FALSE WHERE property_id = ANY(:ids) AND is_current"),
            {"ids": ids}).rowcount
        counts["valuations_retired"] = connection.execute(text(
            "UPDATE property_valuations SET is_current = FALSE WHERE property_id = ANY(:ids) AND is_current"),
            {"ids": ids}).rowcount
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="count what would be flagged; change nothing")
    print(json.dumps(flag(parser.parse_args().dry_run)))


if __name__ == "__main__":
    main()
