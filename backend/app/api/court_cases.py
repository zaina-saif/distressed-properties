"""NY referee foreclosure case summaries (migration 043, built by pipeline.load_queens_pipeline).

The dashboard opens one in place of a sale page for a NY court listing: the case's
summons, Notice of Sale, appearances and auction calendar in one view, with how the
foreclosure moved. Access follows the sale's coverage, as for sale pages.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from app.api.sale_page import require_sale_access
from app.database.session import engine

router = APIRouter(prefix="/api/v1/court-cases", tags=["court-cases"])


@router.get("/{sheriff_sale_id}", dependencies=[Depends(require_sale_access)])
def get_court_case(sheriff_sale_id: str) -> dict[str, Any]:
    with engine.connect() as connection:
        row = connection.execute(text("""SELECT summary, updated_at FROM ny_court_case_summaries
            WHERE sheriff_sale_id::text = :id"""), {"id": sheriff_sale_id}).first()
    if not row:
        raise HTTPException(status_code=404, detail="No court case summary for this sale")
    return {**row[0], "updated_at": row[1].isoformat()}
