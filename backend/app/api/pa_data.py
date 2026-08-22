from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from app.database.session import engine
from pipeline.pa_parcel_numbers import normalize_map_number


router = APIRouter(prefix="/api/v1/pa", tags=["pennsylvania-data"])


@router.get("/sheriff-sales")
def list_pa_sheriff_sales(
    county: str = "Monroe",
    municipality: Optional[str] = None,
    status: Optional[str] = None,
    sale_date_from: Optional[date] = None,
    sale_date_to: Optional[date] = None,
    min_judgment: Optional[Decimal] = None,
    max_judgment: Optional[Decimal] = None,
    matched: Optional[bool] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    conditions = ["s.state='PA'", "s.county=:county"]
    params: dict = {"county": county, "limit": page_size, "offset": (page - 1) * page_size}
    if municipality:
        conditions.append("p.municipality ILIKE :municipality")
        params["municipality"] = f"%{municipality}%"
    if status:
        conditions.append("LOWER(s.current_status)=LOWER(:status)")
        params["status"] = status
    if sale_date_from:
        conditions.append("s.current_sale_date::date>=:sale_date_from")
        params["sale_date_from"] = sale_date_from
    if sale_date_to:
        conditions.append("s.current_sale_date::date<=:sale_date_to")
        params["sale_date_to"] = sale_date_to
    if min_judgment is not None:
        conditions.append("s.judgment_amount>=:min_judgment")
        params["min_judgment"] = min_judgment
    if max_judgment is not None:
        conditions.append("s.judgment_amount<=:max_judgment")
        params["max_judgment"] = max_judgment
    if matched is not None:
        conditions.append("m.id IS NOT NULL" if matched else "m.id IS NULL")
    query = text(f"""SELECT s.id,s.sheriff_number,s.court_case_number,s.property_number,
      s.map_number,s.normalized_map_number,s.plaintiff,s.defendant,s.sale_attorney,
      s.current_sale_date,s.current_status,s.sale_result,s.judgment_amount,s.source_url,
      p.normalized_address,p.municipality,p.city,p.zip_code,
      (m.id IS NOT NULL) AS parcel_matched,m.match_method,m.match_status,
      parcel.map_number AS gis_map_number,parcel.latitude,parcel.longitude,
      d.owner_name,d.assessed_value,d.land_value,d.improvement_value,d.acreage,
      d.property_location,d.last_sale_date,d.last_sale_price,d.assessment_year,
      COUNT(*) OVER() AS total_count
      FROM sheriff_sales s JOIN properties p ON p.id=s.property_id
      LEFT JOIN pa_sheriff_sale_parcel_matches m ON m.sheriff_sale_id=s.id
      LEFT JOIN pa_parcels parcel ON parcel.id=m.parcel_id
      LEFT JOIN pa_property_details d ON d.parcel_id=parcel.id
      WHERE {' AND '.join(conditions)}
      ORDER BY s.current_sale_date,s.sheriff_number LIMIT :limit OFFSET :offset""")
    with engine.connect() as connection:
        items = [dict(row) for row in connection.execute(query, params).mappings()]
    return {"items": items, "total": items[0]["total_count"] if items else 0,
            "page": page, "page_size": page_size}


@router.get("/sheriff-sales/{sale_id}")
def get_pa_sheriff_sale(sale_id: str):
    query = text("""SELECT s.*,p.normalized_address,p.municipality,p.city,p.zip_code,
      (m.id IS NOT NULL) AS parcel_matched,m.match_method,m.match_status,
      parcel.map_number AS gis_map_number,parcel.geometry,parcel.latitude,parcel.longitude,
      d.owner_name,d.assessed_value,d.land_value,d.improvement_value,d.preferential_value,
      d.property_type,d.acreage,d.property_location,d.last_sale_date,d.last_sale_price,
      d.assessment_year,d.enrichment_source
      FROM sheriff_sales s JOIN properties p ON p.id=s.property_id
      LEFT JOIN pa_sheriff_sale_parcel_matches m ON m.sheriff_sale_id=s.id
      LEFT JOIN pa_parcels parcel ON parcel.id=m.parcel_id
      LEFT JOIN pa_property_details d ON d.parcel_id=parcel.id
      WHERE s.id=:sale_id AND s.state='PA'""")
    with engine.connect() as connection:
        row = connection.execute(query, {"sale_id": sale_id}).mappings().first()
    if row is None:
        raise HTTPException(404, "Pennsylvania sheriff sale not found")
    return dict(row)


@router.get("/parcels/{map_number}")
def get_pa_parcel(map_number: str, county: str = "Monroe"):
    normalized = normalize_map_number(map_number)
    query = text("""SELECT parcel.*,d.tax_parcel_id,d.owner_name,d.assessed_value,
      d.land_value,d.improvement_value,d.preferential_value,d.property_type,d.acreage,
      d.property_location,d.last_sale_date,d.last_sale_price,d.assessment_year,
      d.enrichment_source
      FROM pa_parcels parcel LEFT JOIN pa_property_details d ON d.parcel_id=parcel.id
      WHERE parcel.state='PA' AND parcel.county=:county
        AND (parcel.normalized_map_number=:normalized
          OR parcel.normalized_tax_parcel_id=:normalized)""")
    with engine.connect() as connection:
        row = connection.execute(query, {"county": county, "normalized": normalized}).mappings().first()
    if row is None:
        raise HTTPException(404, "Pennsylvania parcel not found")
    return dict(row)


@router.get("/imports/status")
def get_pa_import_status(county: str = "Monroe", limit: int = Query(default=20, ge=1, le=100)):
    with engine.connect() as connection:
        runs = connection.execute(text("""SELECT id,job_name,county,source_system,started_at,
          completed_at,status,records_found,records_created,records_updated,records_failed
          FROM scrape_runs WHERE county=:county ORDER BY started_at DESC LIMIT :limit"""),
          {"county": county, "limit": limit}).mappings()
        parcel_count = connection.execute(text("""SELECT COUNT(*) FROM pa_parcels
          WHERE state='PA' AND county=:county"""), {"county": county}).scalar_one()
        detail_count = connection.execute(text("""SELECT COUNT(*) FROM pa_property_details d
          JOIN pa_parcels p ON p.id=d.parcel_id WHERE p.state='PA' AND p.county=:county"""),
          {"county": county}).scalar_one()
    return {"county": county, "parcel_count": parcel_count,
            "assessment_detail_count": detail_count, "sheriff_imports": [dict(row) for row in runs]}
