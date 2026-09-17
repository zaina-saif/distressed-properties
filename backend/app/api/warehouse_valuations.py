"""Read-only historical-property coverage and state AVM review endpoints."""
from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from app.database.session import warehouse_engine
from pipeline.state_avm_scope import residential_scope

router = APIRouter(prefix="/api/v1/warehouse-valuations", tags=["warehouse-valuations"])
State = Literal["MD", "NY", "IL", "FL", "OH", "VA", "DC"]
MODEL_DIR = Path(__file__).resolve().parents[2] / "data" / "state_avm" / "models"


def model_run(connection: Any, state: str, promoted_only: bool = False) -> dict[str, Any] | None:
    condition = "AND status='PROMOTED'" if promoted_only else ""
    row = connection.execute(text(f"""SELECT status,model_version,artifact_path,row_counts,metrics,
                                         data_as_of,trained_at
                                  FROM state_avm_model_runs WHERE state=:state {condition}
                                  ORDER BY trained_at DESC LIMIT 1"""), {"state": state}).mappings().first()
    if row is None:
        return None
    return {**dict(row), "data_as_of": row["data_as_of"].isoformat() if row["data_as_of"] else None,
            "trained_at": row["trained_at"].isoformat() if row["trained_at"] else None}


@router.get("/coverage")
def coverage(state: State) -> dict[str, Any]:
    today = date.today()
    with warehouse_engine.connect() as connection:
        rows = connection.execute(text("""SELECT year,sale_count,sale_counties,snapshot_count,
                  snapshot_counties,first_sale,last_sale,refreshed_at
                  FROM public_property_coverage_yearly WHERE state=:state
                    AND year BETWEEN 2020 AND :year ORDER BY year"""),
                                  {"state": state, "year": today.year}).mappings().all()
        state_row = connection.execute(text("""SELECT future_dated_sales,refreshed_at
                  FROM public_property_coverage_state WHERE state=:state"""),
                                       {"state": state}).mappings().first()
        latest_run = model_run(connection, state)
    if latest_run:
        latest_run.pop("artifact_path", None)
    by_year = {row["year"]: row for row in rows}
    years = []
    for year in range(2020, today.year + 1):
        row = by_year.get(year)
        years.append({
            "year": year,
            "sales": int(row["sale_count"]) if row else 0,
            "sale_counties": int(row["sale_counties"]) if row else 0,
            "snapshots": int(row["snapshot_count"]) if row else 0,
            "snapshot_counties": int(row["snapshot_counties"]) if row else 0,
            "first_sale": row["first_sale"].isoformat() if row and row["first_sale"] else None,
            "last_sale": row["last_sale"].isoformat() if row and row["last_sale"] else None,
        })
    refreshed = max((row["refreshed_at"] for row in rows), default=None)
    return {
        "state": state, "as_of": today.isoformat(), "years": years,
        "refreshed_at": refreshed.isoformat() if refreshed else None,
        "future_dated_sales": int(state_row["future_dated_sales"]) if state_row else 0,
        "total_sales": sum(item["sales"] for item in years),
        "total_snapshots": sum(item["snapshots"] for item in years),
        "latest_sale": max((item["last_sale"] for item in years if item["last_sale"]), default=None),
        "model": latest_run,
        "coverage_note": "Counts are source records, not unique properties. A nonzero year does not prove every county or month is complete.",
    }


@router.get("/counties")
def counties(state: State, year: int = Query(ge=2020, le=2100)) -> dict[str, Any]:
    with warehouse_engine.connect() as connection:
        names = connection.execute(text("""SELECT snapshot_county_names
                 FROM public_property_coverage_yearly WHERE state=:state AND year=:year"""),
                                   {"state": state, "year": year}).scalar_one_or_none()
    return {"state": state, "year": year, "counties": names or []}


@router.get("/months")
def months(state: State, county: str = Query(min_length=1),
           year: int = Query(ge=2020, le=2100)) -> dict[str, Any]:
    today = date.today()
    if year > today.year:
        raise HTTPException(422, "Future sale years cannot be reviewed")
    with warehouse_engine.connect() as connection:
        rows = connection.execute(text("""SELECT EXTRACT(MONTH FROM sale_date)::int AS month,
               COUNT(*) AS record_count,MIN(sale_date) AS first_date,MAX(sale_date) AS last_date
               FROM public_property_sales
               WHERE state=:state AND county=:county AND sale_date>=:start_date
                 AND sale_date<:end_date AND sale_date<=:today
               GROUP BY 1 ORDER BY 1"""),
            {"state": state, "county": county, "start_date": date(year, 1, 1),
             "end_date": date(year + 1, 1, 1), "today": today}).mappings().all()
    by_month = {row["month"]: row for row in rows}
    last_month = today.month if year == today.year else 12
    return {"state": state, "county": county, "year": year,
            "months": [{"month": month,
                        "sales": int(by_month[month]["record_count"]) if month in by_month else 0,
                        "first_sale": by_month[month]["first_date"].isoformat() if month in by_month else None,
                        "last_sale": by_month[month]["last_date"].isoformat() if month in by_month else None}
                       for month in range(1, last_month + 1)],
            "note": "Zero records flag a possible coverage gap, but nonzero counts do not prove a complete download."}


@lru_cache(maxsize=14)
def load_model(path: str, modified_ns: int) -> dict[str, Any]:
    import joblib
    return joblib.load(path)


def score_current_rows(rows: list[dict[str, Any]], run: dict[str, Any] | None, today: date) -> None:
    if not rows:
        return
    artifact = Path(run["artifact_path"]).resolve() if run and run.get("artifact_path") else None
    if not artifact or artifact.parent != MODEL_DIR.resolve() or not artifact.is_file():
        for row in rows:
            row["estimate_status"] = "MODEL_NOT_AVAILABLE"
        return
    import numpy as np
    import pandas as pd

    model = load_model(str(artifact), artifact.stat().st_mtime_ns)
    features = model["features"]
    frame = pd.DataFrame(rows)
    frame["sale_year"] = today.year
    frame["sale_month"] = today.month
    frame["property_age"] = today.year - pd.to_numeric(frame["year_built"], errors="coerce")
    frame["prior_sale_price"] = pd.to_numeric(frame["last_sale_price"], errors="coerce")
    previous = pd.to_datetime(frame["last_sale_date"], errors="coerce")
    frame["prior_sale_age_years"] = (pd.Timestamp(today) - previous).dt.days / 365.25
    for name in features:
        if name not in frame:
            frame[name] = np.nan
    numeric = {"living_area", "land_area", "bedrooms", "bathrooms", "rooms", "year_built",
               "land_value", "improvement_value", "total_assessed_value", "latitude", "longitude",
               "sale_month", "sale_year", "property_age", "prior_sale_price",
               "prior_sale_age_years"}
    for name in features:
        if name in numeric:
            frame[name] = pd.to_numeric(frame[name], errors="coerce")
        else:
            frame[name] = frame[name].replace("", np.nan)
    predictions = model["pipeline"].predict(frame[features])
    if model["target_transform"] == "log1p":
        predictions = np.expm1(predictions)
    for row, prediction in zip(rows, predictions):
        if model.get("segment") == "residential" and not residential_scope(
                row["state"], row.get("source_id"), row.get("land_use_code")):
            row["estimate_status"] = "OUT_OF_MODEL_SCOPE"
            row["model_version"] = model["model_version"]
            continue
        has_building_detail = any(row.get(field) is not None for field in (
            "living_area", "bedrooms", "bathrooms", "year_built"))
        has_price_anchor = bool(row.get("last_sale_price") and row["last_sale_price"] > 0)
        has_assessment = bool(row.get("total_assessed_value") and row["total_assessed_value"] > 0)
        if not (has_price_anchor or (has_building_detail and (has_assessment or row.get("zip_code")))):
            row["estimate_status"] = "LOW_FEATURE_COVERAGE"
            row["model_version"] = model["model_version"]
            continue
        value = float(prediction)
        row["estimated_price"] = round(value, 2) if np.isfinite(value) and value > 0 else None
        row["estimate_status"] = "SCORED" if row["estimated_price"] is not None else "SCORING_FAILED"
        row["model_version"] = model["model_version"]


def apply_address_matches(items: list[dict[str, Any]], matches: list[Any]) -> None:
    by_parcel = {row["source_parcel_id"]: row for row in matches}
    for item in items:
        if item["street_address"] and item["city"] and item["zip_code"]:
            continue
        match = by_parcel.get(item["source_parcel_id"])
        if not match:
            continue
        had_street = bool(item["street_address"])
        had_city = bool(item["city"])
        had_zip = bool(item["zip_code"])
        item["street_address"] = item["street_address"] or match["street_address"]
        item["city"] = item["city"] or match["city"]
        item["zip_code"] = item["zip_code"] or match["zip_code"]
        if not had_street and item["street_address"]:
            item["house_number_unavailable"] = match["house_number_unavailable"]
        if ((not had_street and item["street_address"]) or
                (not had_city and item["city"]) or (not had_zip and item["zip_code"])):
            item["address_source_id"] = match["source_id"]
            item["address_snapshot_year"] = match["snapshot_year"]


@router.get("/properties")
def properties(state: State, year: int = Query(ge=2020, le=2100), county: str = Query(min_length=1),
               after_parcel: str | None = None, after_source: str | None = None,
               q: Annotated[str | None, Query(max_length=120)] = None,
               page_size: Annotated[int, Query(ge=1, le=100)] = 25) -> dict[str, Any]:
    today = date.today()
    if year > today.year:
        raise HTTPException(422, "Future snapshot years cannot be reviewed")
    search = f"%{q.strip()}%" if q and q.strip() else None
    with warehouse_engine.connect() as connection:
        rows = connection.execute(text("""WITH page AS (
             SELECT source_id,state,county,source_parcel_id,snapshot_year,street_address,city,
                    zip_code,property_type,land_use_code,year_built,living_area,land_area,
                    house_number_unavailable,
                    bedrooms,bathrooms,rooms,land_value,improvement_value,total_assessed_value,
                    latitude,longitude,school_district_code,school_district_name
             FROM public_property_snapshots
             WHERE state=:state AND county=:county AND snapshot_year=:year
               AND (:after_parcel IS NULL OR (source_parcel_id,source_id) > (:after_parcel,:after_source))
               AND (:search IS NULL OR street_address ILIKE :search OR source_parcel_id ILIKE :search)
             ORDER BY source_parcel_id,source_id LIMIT :limit
           ) SELECT page.*,sale.sale_date AS last_sale_date,sale.sale_price AS last_sale_price
           FROM page LEFT JOIN LATERAL (
             SELECT sale_date,sale_price FROM public_property_sales s
             WHERE s.state=page.state AND s.county=page.county
               AND s.source_parcel_id=page.source_parcel_id AND s.sale_date<=:today
             ORDER BY sale_date DESC,id DESC LIMIT 1
           ) sale ON TRUE ORDER BY page.source_parcel_id,page.source_id"""),
            {"state": state, "county": county, "year": year, "after_parcel": after_parcel,
             "after_source": after_source, "search": search, "limit": page_size + 1, "today": today}).mappings().all()
        active_model = model_run(connection, state, promoted_only=True) if year == today.year else None
    has_more = len(rows) > page_size
    items = [dict(row) for row in rows[:page_size]]
    missing_address_ids = list({item["source_parcel_id"] for item in items
                                if not (item["street_address"] and item["city"] and item["zip_code"])})
    if missing_address_ids:
        with warehouse_engine.connect() as connection:
            address_matches = connection.execute(text("""WITH candidates AS (
                  SELECT source_parcel_id,source_id,snapshot_year,street_address,city,zip_code,
                         house_number_unavailable,imported_at,0 AS priority
                  FROM public_property_snapshots
                  WHERE state=:state AND county=:county AND snapshot_year<=:year
                    AND source_parcel_id=ANY(:parcels)
                    AND (NULLIF(BTRIM(street_address),'') IS NOT NULL
                         OR city IS NOT NULL OR zip_code IS NOT NULL)
                  UNION ALL
                  SELECT source_parcel_id,source_id,as_of_year AS snapshot_year,
                         street_address,city,zip_code,house_number_unavailable,
                         imported_at,1 AS priority
                  FROM public_parcel_addresses
                  WHERE state=:state AND county=:county AND as_of_year<=:year
                    AND source_parcel_id=ANY(:parcels)
                ) SELECT DISTINCT ON (source_parcel_id)
                  source_parcel_id,source_id,snapshot_year,street_address,city,zip_code,
                  house_number_unavailable
                FROM candidates
                ORDER BY source_parcel_id,
                  (NULLIF(BTRIM(street_address),'') IS NOT NULL) DESC,
                  snapshot_year DESC,priority DESC,imported_at DESC"""),
                {"state": state, "county": county, "year": year,
                 "parcels": missing_address_ids}).mappings().all()
        apply_address_matches(items, address_matches)
    # The public NY parcel layer is a 2025 assessment. It may describe a 2026
    # SalesWeb property, but must never be projected backward onto older sales.
    if state == "NY" and year > 2025 and items:
        with warehouse_engine.connect() as connection:
            feature_rows = connection.execute(text("""SELECT DISTINCT ON (source_parcel_id)
                  source_parcel_id,snapshot_year,bedrooms,bathrooms,living_area,year_built
                FROM public_property_snapshots
                WHERE source_id='ny_nys_gis_tax_parcels_2025'
                  AND state='NY' AND county=:county AND snapshot_year<:year
                  AND source_parcel_id=ANY(:parcels)
                ORDER BY source_parcel_id,snapshot_year DESC"""),
                {"county": county, "year": year,
                 "parcels": list({item["source_parcel_id"] for item in items})}).mappings().all()
        features = {row["source_parcel_id"]: row for row in feature_rows}
        for item in items:
            feature = features.get(item["source_parcel_id"])
            if feature:
                copied = False
                for field in ("bedrooms", "bathrooms", "living_area", "year_built"):
                    if item[field] is None and feature[field] is not None:
                        item[field] = feature[field]
                        copied = True
                if copied:
                    item["feature_source_id"] = "ny_nys_gis_tax_parcels_2025"
                    item["feature_snapshot_year"] = feature["snapshot_year"]
    for item in items:
        item["last_sale_date"] = item["last_sale_date"].isoformat() if item["last_sale_date"] else None
        for field in ("last_sale_price", "land_area", "bedrooms", "bathrooms", "rooms",
                      "land_value", "improvement_value", "total_assessed_value"):
            if item[field] is not None:
                item[field] = float(item[field])
        item["estimated_price"] = None
        item["estimate_status"] = "HISTORICAL_NOT_SCORED" if year != today.year else "MODEL_NOT_AVAILABLE"
        item["model_version"] = None
    if year == today.year:
        score_current_rows(items, active_model, today)
    last = items[-1] if items and has_more else None
    return {"items": items, "next_cursor": {"parcel": last["source_parcel_id"], "source": last["source_id"]} if last else None,
            "state": state, "county": county, "year": year,
            "note": "Current-year estimates use the latest promoted state model. Historical snapshots are not scored with a model trained on future sales."}
