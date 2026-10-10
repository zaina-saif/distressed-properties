"""Sale results: the winning bid and who bought, for sales that were sold.

Sources, in order of trust:
  1. The sale page's "Status History" table (CivilView), saved in
     sheriff_sales.description_text. Its sold row carries the amount:
         Purchased - 3rd Party
         10/1/2025
         $427,000.00
  2. The status text itself, which some sheriffs write out in full
     ("SOLD: 3RD PARTY FOR $ 68,100.00", "SOLD TO PLAINTIFF FOR $148,100").

The buyer comes from the same status text. A plaintiff (lender) usually bids a
nominal amount such as $100 to take the property back, so analytics compare
third-party bids only. A "$0.00" amount means none was published.

    python -m pipeline.sale_results            # fill every sold sale
    python -m pipeline.sale_results --dry-run  # counts only
"""
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Iterable, Optional

SOLD_STATUS = re.compile(r"\b(?:sold|purchased)\b", re.IGNORECASE)
# A sold row in the CivilView Status History table: status, date, amount.
HISTORY_ROW = re.compile(
    r"^[ \t]*((?:Purchased|Sold)\b[^\n]*)\n[ \t]*(\d{1,2}/\d{1,2}/\d{4})[ \t]*\n[ \t]*\$\s*([\d,]+(?:\.\d{2})?)",
    re.IGNORECASE | re.MULTILINE,
)
AMOUNT_IN_STATUS = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")


@dataclass(frozen=True)
class SaleResult:
    buyer: str
    amount: Optional[Decimal]
    sold_on: Optional[date]
    raw_status: str


def classify_buyer(raw_status: str) -> str:
    text = raw_status.lower()
    if "cwpp" in text:
        return "cwpp"
    if re.search(r"3rd\s*party|third\s*party", text):
        return "third_party"
    if re.search(r"plaintiff|buy\s*back|fha/hud", text):
        return "plaintiff"
    return "not_stated"


def _money(value: str) -> Optional[Decimal]:
    try:
        amount = Decimal(value.replace(",", "").strip())
    except InvalidOperation:
        return None
    return amount if amount > 0 else None


def _date(value: str) -> Optional[date]:
    try:
        return datetime.strptime(value, "%m/%d/%Y").date()
    except ValueError:
        return None


def parse_sale_result(description_text: Optional[str], raw_statuses: Iterable[str] = (),
                      sale_date: Optional[date] = None) -> Optional[SaleResult]:
    """The sale's result, or None when nothing says it was sold.

    `raw_statuses` are the sale's status texts, oldest first; the last sold one wins.
    """
    rows = HISTORY_ROW.findall(description_text or "")
    if rows:
        status, sold_on, amount = rows[-1]
        status = status.strip()
        return SaleResult(classify_buyer(status), _money(amount), _date(sold_on) or sale_date, status)
    sold = [status.strip() for status in raw_statuses if status and SOLD_STATUS.search(status)]
    if not sold:
        return None
    status = sold[-1]
    match = AMOUNT_IN_STATUS.search(status)
    return SaleResult(classify_buyer(status), _money(match.group(1)) if match else None, sale_date, status)


def backfill(dry_run: bool = False) -> dict[str, int]:
    """Fill sold_* on every sale whose status says it was sold. Safe to rerun."""
    from sqlalchemy import text

    from app.database.session import engine

    with engine.connect() as connection:
        sales = connection.execute(text("""
            SELECT ss.id, ss.description_text, ss.current_sale_date,
                   COALESCE(ARRAY_AGG(h.raw_status ORDER BY h.sale_date NULLS FIRST, h.observed_at, h.id)
                            FILTER (WHERE h.raw_status IS NOT NULL), '{}') AS raw_statuses
            FROM sheriff_sales ss
            LEFT JOIN sheriff_sale_status_history h ON h.sheriff_sale_id = ss.id
            WHERE (ss.current_status ILIKE 'sold%' OR ss.current_status ILIKE 'purchased%')
              AND ss.current_status NOT ILIKE '%unverified%'
            GROUP BY ss.id
        """)).mappings().all()
    counts = {"sold_sales": len(sales), "with_result": 0, "with_amount": 0}
    updates = []
    for sale in sales:
        sale_date = sale["current_sale_date"].date() if sale["current_sale_date"] else None
        result = parse_sale_result(sale["description_text"], sale["raw_statuses"], sale_date)
        if result is None:
            continue
        counts["with_result"] += 1
        counts["with_amount"] += result.amount is not None
        updates.append({"id": sale["id"], "amount": result.amount, "buyer": result.buyer,
                        "sold_on": result.sold_on, "raw_status": result.raw_status})
    if dry_run:
        return counts
    # Short transactions: one long one can outlive the Supabase pooler connection.
    for start in range(0, len(updates), 500):
        with engine.begin() as connection:
            connection.execute(text("""
                UPDATE sheriff_sales
                SET sold_amount = :amount, sold_buyer = :buyer, sold_on = :sold_on, sold_raw_status = :raw_status
                WHERE id = :id
            """), updates[start:start + 500])
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="Parse and count without writing")
    counts = backfill(parser.parse_args().dry_run)
    print(f"Sold sales: {counts['sold_sales']}, with a result: {counts['with_result']}, "
          f"with a winning bid: {counts['with_amount']}")


if __name__ == "__main__":
    main()
