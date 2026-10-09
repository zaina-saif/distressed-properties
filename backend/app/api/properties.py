import json
import math
import os
from io import BytesIO
from typing import Literal, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from openpyxl import Workbook
from pydantic import BaseModel
from sqlalchemy import text

from app.auth import Access, require_access, require_developer, require_property_access
from app.rate_limit import per_user
from app.database.session import engine


router = APIRouter(
    prefix="/api/v1/properties",
    tags=["properties"],
)

EXPORT_FIELDS = [
    ("Distress source", "sale_type"),
    ("Estimated Market Value", "apify_data.zestimate"),
    ("Minimum bid amount", "minimum_asking_amount"),
    ("Gross equity", "gross_equity"), ("Gross equity %", "gross_equity_percent"),
    ("Description", "apify_data.description"),
    ("Address", "normalized_address"), ("County", "county"),
    ("Status", "current_status"), ("Sale date", "current_sale_date"),
    ("Court case", "court_case_number"), ("Plaintiff", "plaintiff"), ("Defendant", "defendant"),
    ("Time in distress", "distress_duration_days"),
    ("Probability to auction", "sale_probability"),
    ("Valuation retrieved", "valuation_retrieved_at"), ("Lien risk summary", "lien_risk_calculated_at"),
]
APIFY_EXPORT_KEYS = [
    "homeType", "lastSoldPrice", "bedrooms", "bathrooms", "livingArea", "yearBuilt",
]


def readable_apify_value(value, depth=0):
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (int, float)):
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        shown = [readable_apify_value(item, depth + 1) for item in value[:4]]
        result = " | ".join(item for item in shown if item)
        if len(value) > 4:
            result += f" | +{len(value) - 4} more"
        return result
    if depth >= 2:
        return json.dumps(value, default=str)
    parts = []
    for key, item in value.items():
        label = "".join(f" {char.lower()}" if char.isupper() else char for char in key).capitalize()
        parts.append(f"{label}: {readable_apify_value(item, depth + 1)}")
    return "; ".join(parts)


class ParcelApproval(BaseModel):
    candidate_id: int

@router.get("/parcel-review/candidates", dependencies=[Depends(require_developer)])
def list_parcel_review_candidates():
    query=text("""SELECT p.id property_id,p.normalized_address,p.city,p.zip_code,
      bool_or(lower(ss.current_status)='scheduled') is_scheduled,
      bool_or(pv.id IS NULL) missing_valuation,
      jsonb_agg(jsonb_build_object('candidate_id',c.id,'rank',c.rank,
        'score',c.match_score,'municipality_code',c.municipality_code,
        'block',c.block,'lot',c.lot,'qualifier',c.qualifier,
        'property_location',c.property_location) ORDER BY c.rank) candidates
      FROM property_parcel_candidates c JOIN properties p ON p.id=c.property_id
      JOIN sheriff_sales ss ON ss.property_id=p.id
      LEFT JOIN LATERAL(SELECT id FROM property_valuations WHERE property_id=p.id AND is_current LIMIT 1)pv ON TRUE
      WHERE c.review_status='PENDING'
        AND NOT EXISTS (SELECT 1 FROM sheriff_sale_parcels ssp
          WHERE ssp.sheriff_sale_id=ss.id
            AND ssp.match_status IN ('VERIFIED','MANUALLY_VERIFIED'))
      GROUP BY p.id,p.normalized_address,p.city,p.zip_code
      ORDER BY bool_or(lower(ss.current_status)='scheduled') DESC,
       bool_or(pv.id IS NULL) DESC,p.normalized_address""")
    with engine.connect() as connection:
        return {"items":[dict(row) for row in connection.execute(query).mappings()]}

@router.post("/{property_id}/parcel-review/approve", dependencies=[Depends(require_developer)])
def approve_parcel_candidate(property_id: str,approval: ParcelApproval):
    with engine.begin() as connection:
        candidate=connection.execute(text("""SELECT * FROM property_parcel_candidates
          WHERE id=:candidate_id AND property_id=:property_id AND review_status='PENDING'
          FOR UPDATE"""),{"candidate_id":approval.candidate_id,"property_id":property_id}).mappings().first()
        if candidate is None: raise HTTPException(404,"Pending parcel candidate not found")
        feature=dict(candidate["parcel_features"])
        connection.execute(text("""UPDATE properties SET block=:block,lot=:lot,qualifier=:qualifier,
          pams_pin=:pams_pin,identity_confidence=85,updated_at=NOW() WHERE id=:property_id"""),
          {"property_id":property_id,"block":candidate["block"],"lot":candidate["lot"],
           "qualifier":candidate["qualifier"],"pams_pin":f'{candidate["municipality_code"].strip()}_{candidate["block"]}_{candidate["lot"]}'+(f'_{candidate["qualifier"]}' if candidate["qualifier"] else '')})
        params={"property_id":property_id,"snapshot_year":feature["source_year"],
          "municipality_code":candidate["municipality_code"],"block":candidate["block"],"lot":candidate["lot"],
          "qualifier":candidate["qualifier"],"property_class":feature.get("property_class"),
          "property_location":candidate["property_location"],"acreage":feature.get("acreage"),
          "zoning":feature.get("zoning"),"building_class":feature.get("building_class"),
          "year_built":feature.get("year_built"),"land_assessed":feature.get("land_assessed"),
          "improvement_assessed":feature.get("improvement_assessed"),"total_assessed":feature.get("total_assessed"),
          "annual_property_tax":feature.get("annual_property_tax"),"census_tract":feature.get("census_tract"),
          "property_use_code":feature.get("property_use_code"),"source_hash":candidate["source_hash"]}
        connection.execute(text("""INSERT INTO property_avm_features(property_id,snapshot_year,municipality_code,
          block,lot,qualifier,property_class,property_location,acreage,zoning,building_class,year_built,
          land_assessed,improvement_assessed,total_assessed,annual_property_tax,census_tract,property_use_code,
          match_method,match_confidence,source_hash) VALUES(:property_id,:snapshot_year,:municipality_code,
          :block,:lot,:qualifier,:property_class,:property_location,:acreage,:zoning,:building_class,:year_built,
          :land_assessed,:improvement_assessed,:total_assessed,:annual_property_tax,:census_tract,:property_use_code,
          'manual candidate approval',85,:source_hash) ON CONFLICT(property_id) DO UPDATE SET
          municipality_code=EXCLUDED.municipality_code,block=EXCLUDED.block,lot=EXCLUDED.lot,
          qualifier=EXCLUDED.qualifier,property_location=EXCLUDED.property_location,
          match_method=EXCLUDED.match_method,match_confidence=EXCLUDED.match_confidence,
          source_hash=EXCLUDED.source_hash,matched_at=NOW()"""),params)
        connection.execute(text("""UPDATE property_parcel_candidates SET review_status=CASE WHEN id=:id
          THEN 'APPROVED' ELSE 'REJECTED' END,reviewed_at=NOW() WHERE property_id=:property_id
          AND review_status='PENDING'"""),{"id":approval.candidate_id,"property_id":property_id})
    return {"status":"approved","property_id":property_id,"candidate_id":approval.candidate_id}


# NJ minimum bid: the portal's "Approx. Upset*" (stored as upset_price), else
# the judgment amount, else an upset figure quoted in the sale notice. Other
# states keep the largest parsed upset.
UPSET_SQL = (
    "(CASE WHEN ss.state='NJ' THEN ss.upset_price "
    "ELSE GREATEST(ss.estimated_upset_price, ss.alternate_upset_price, ss.upset_price) END)"
)
MINIMUM_BID_SQL = (
    "(CASE WHEN ss.state='NJ' THEN COALESCE(ss.upset_price, ss.judgment_amount, "
    "GREATEST(ss.estimated_upset_price, ss.alternate_upset_price)) "
    "ELSE COALESCE(GREATEST(ss.estimated_upset_price, ss.alternate_upset_price, ss.upset_price), "
    "ss.judgment_amount) END)"
)
MINIMUM_BID_BASIS_SQL = (
    "(CASE WHEN ss.state<>'NJ' THEN NULL "
    "WHEN ss.upset_price IS NOT NULL THEN 'approx_upset' "
    "WHEN ss.judgment_amount IS NOT NULL THEN 'judgment' "
    "WHEN COALESCE(ss.estimated_upset_price, ss.alternate_upset_price) IS NOT NULL THEN 'notice_estimate' END)"
)

# Sale status as shown: unverified secondary-source listings whose date has passed read as date_passed_unverified.
EFFECTIVE_STATUS_SQL = "LOWER(CASE WHEN ss.source_system IN ('nyc_kings_court_foreclosure_index','fl_hillsborough_published_foreclosure_notice') AND ss.current_sale_date<CURRENT_DATE AND ss.current_status='scheduled_unverified' THEN 'date_passed_unverified' ELSE ss.current_status END)"

# Investor Spotlight ranks by expected equity: gross equity (Zestimate minus the
# minimum bid) weighted by the probability that the next sale date goes to auction.
SPOTLIGHT_GROSS_EQUITY = f"(azr.zestimate - {MINIMUM_BID_SQL})"
SPOTLIGHT_SCORE = f"(sp.probability * {SPOTLIGHT_GROSS_EQUITY})"


@router.get("", dependencies=[Depends(per_user("property_list", 600))])
def list_properties(
    state: list[str] = Query(default=[]),
    county: list[str] = Query(default=[]),
    q: Optional[str] = Query(default=None, max_length=200),
    zip_code: Optional[str] = None,
    status: Optional[str] = None,
    status_contains: Optional[str] = Query(default=None, max_length=100),
    future_only: bool = False,
    min_equity: Optional[float] = None,
    max_risk: Optional[int] = None,
    investor_spotlight: bool = False,
    sort: str = "sale-date",
    sort_direction: Literal["asc", "desc"] = "asc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    access: Access = Depends(require_access),
):
    offset = (page - 1) * page_size

    conditions = ["ss.property_id IS NOT NULL"]
    parameters = {
        "limit": page_size,
        "offset": offset,
    }

    # The plan's coverage always applies, on top of any filters in the request.
    if access.scope_state:
        conditions.append("p.state = :scope_state")
        parameters["scope_state"] = access.scope_state
    if access.scope_county:
        conditions.append("LOWER(p.county) = :scope_county")
        parameters["scope_county"] = access.scope_county.lower()

    if state:
        conditions.append("p.state = ANY(:states)")
        parameters["states"] = [value.upper() for value in state]

    if county:
        conditions.append("LOWER(p.county) = ANY(:counties)")
        parameters["counties"] = [value.lower() for value in county]

    if q and q.strip():
        conditions.append(
            "(p.normalized_address ILIKE :search OR "
            "p.street_address ILIKE :search OR "
            "p.city ILIKE :search OR "
            "p.county ILIKE :search OR "
            "p.zip_code ILIKE :search OR "
            "ss.sheriff_number ILIKE :search OR "
            "COALESCE(ss.docket_number, ss.court_case_number) ILIKE :search OR "
            "ss.plaintiff ILIKE :search OR "
            "ss.defendant ILIKE :search)"
        )
        parameters["search"] = f"%{q.strip()}%"

    if zip_code:
        conditions.append("p.zip_code = :zip_code")
        parameters["zip_code"] = zip_code

    effective_status = EFFECTIVE_STATUS_SQL
    if status:
        conditions.append(f"{effective_status} = :status")
        parameters["status"] = status.lower()

    if status_contains and status_contains.strip():
        conditions.append(f"strpos({effective_status}, :status_contains) > 0")
        parameters["status_contains"] = status_contains.strip().lower()

    if future_only:
        conditions.append("ss.current_sale_date >= CURRENT_DATE")

    if min_equity is not None:
        conditions.append(f"azr.zestimate - CASE WHEN ss.state='IL' THEN ss.upset_price ELSE {MINIMUM_BID_SQL} END >= :min_equity")
        parameters["min_equity"] = min_equity

    if max_risk is not None:
        conditions.append("ra.risk_score <= :max_risk")
        parameters["max_risk"] = max_risk

    if investor_spotlight:
        # Upcoming scheduled sales with positive gross equity and a probability score.
        conditions.append(f"strpos({effective_status}, 'scheduled') > 0")
        conditions.append("ss.current_sale_date >= CURRENT_DATE")
        conditions.append(f"{SPOTLIGHT_GROSS_EQUITY} > 0")
        conditions.append("sp.probability IS NOT NULL")

    where_clause = " AND ".join(conditions)
    sort_columns = {
        "sheriff-number": "ss.sheriff_number",
        "address": "p.normalized_address", "street-address": "p.street_address",
        "city": "p.city", "county": "p.county", "state": "p.state", "zip": "p.zip_code",
        "lakefront": "CASE WHEN p.normalized_address ~* '\\m(LAKEFRONT|LAKE[[:space:]]+FRONT|LAKESHORE|LAKE[[:space:]]+SHORE|LAKESIDE)\\M' THEN 1 ELSE 0 END",
        "court-case": "court_case_number", "status": "ss.current_status",
        "bbl": "ss.property_number",
        "sale-type": "CASE WHEN ss.source_system='nyc_nyctl_referee_sales' THEN 'Referee tax-lien auction' WHEN ss.source_system='nyc_kings_court_foreclosure_index' THEN 'Court foreclosure auction' WHEN ss.source_system='fl_hillsborough_published_foreclosure_notice' THEN 'Foreclosure auction (published notice)' WHEN ss.source_system='fl_columbia_clerk_foreclosure' THEN 'Foreclosure auction' WHEN ss.source_system='fl_palm_beach_sheriff_execution' THEN 'Sheriff execution sale' WHEN ss.source_system='fl_fdot_surplus_property' THEN 'FDOT surplus property' WHEN ss.source_system='fl_swfwmd_land_for_sale' THEN 'Government land for sale' WHEN ss.source_system='fl_us_treasury_real_property' THEN 'Federal seized-property auction' ELSE 'Sheriff sale' END",
        "sale-date": "ss.current_sale_date", "plaintiff": "ss.plaintiff", "defendant": "ss.defendant",
        "estimated-market-value": "market_value", "value-range-low": "market_value_low",
        "value-range-high": "market_value_high", "valuation-provider": "valuation_provider",
        "valuation-confidence": "valuation_confidence", "valuation-status": "valuation_status",
        "valuation-note": "valuation_pending_reason", "upset-price": "upset_price",
        "minimum-bid-amount": MINIMUM_BID_SQL,
        "opening-bid": "CASE WHEN ss.state='IL' THEN ss.upset_price END",
        "judgment-amount": "ss.judgment_amount", "starting-bid": "ss.starting_bid", "gross-equity": "gross_equity",
        "distress-duration": "COALESCE(status_dates.latest_scheduled_date, ss.distress_start_date, make_date(ss.distress_start_year, 1, 1))",
        "notice-lien-amount": "ss.notice_lien_amount",
        "avm-judgment-spread": "avm_judgment_spread",
        "gross-equity-percent": "gross_equity_percent", "probability-to-auction": "sale_probability",
        "overall-risk-score": "ra.risk_score", "overall-risk-level": "ra.risk_level",
        "lien-risk-score": "lrr.risk_score", "lien-risk-level": "lrr.risk_level",
        "lien-risk-confidence": "lrr.confidence_score", "total-lien-amount": "lc.total_lien_amount",
        "known-lien-exposure": "lrr.known_exposure", "lien-records": "lc.lien_record_count",
        "open-liens": "lc.open_lien_count", "potentially-surviving-liens": "lc.potentially_surviving_count",
        "lien-manual-review": "lc.manual_review_count", "lienholders-and-claims": "lc.lien_items::text",
        "property-type": "p.property_type", "bedrooms": "p.bedrooms", "bathrooms": "p.bathrooms",
        "square-feet": "p.square_feet", "acreage": "acreage", "year-built": "year_built",
        "pams-pin": "pams_pin", "block": "block", "lot": "lot", "qualifier": "qualifier",
        "parcel-match-confidence": "f.match_confidence", "latitude": "latitude", "longitude": "longitude",
        "coordinate-source": "coordinate_source", "valuation-retrieved": "valuation_retrieved_at",
        "lien-risk-calculated": "lien_risk_calculated_at", "lien-risk-summary": "lien_risk_calculated_at",
        "foreclosure-source": "ss.source_url",
        "investor-spotlight": SPOTLIGHT_SCORE,
        # Backward-compatible values used by the existing sort menu.
        "value-desc": "market_value", "equity-desc": "gross_equity",
    }
    if sort not in sort_columns:
        raise HTTPException(status_code=422, detail=f"Unsupported sort column: {sort}")
    direction = sort_direction.upper()
    order_by = f"{sort_columns[sort]} {direction} NULLS LAST, p.normalized_address ASC"

    query = text(
        f"""
        SELECT
            p.id AS property_id,
            ss.id AS sheriff_sale_id,
            p.normalized_address,
            p.street_address,
            p.city,
            p.county,
            p.state,
            p.zip_code,
            p.property_type,
            p.bedrooms,
            p.bathrooms,
            p.square_feet,
            COALESCE(canonical_parcel.acreage, f.acreage, p.acreage) AS acreage,
            COALESCE(canonical_parcel.year_built, f.year_built, p.year_built) AS year_built,
            canonical_parcel.pams_pin,
            COALESCE(canonical_parcel.block, p.block) AS block,
            COALESCE(canonical_parcel.lot, p.lot) AS lot,
            canonical_parcel.qualifier,
            COALESCE(canonical_parcel.latitude, avm_subject.latitude, p.latitude,
                     (azr.raw_payload->'coordinates'->>'latitude')::DOUBLE PRECISION)
                AS latitude,
            COALESCE(canonical_parcel.longitude, avm_subject.longitude, p.longitude,
                     (azr.raw_payload->'coordinates'->>'longitude')::DOUBLE PRECISION)
                AS longitude,
            CASE
                WHEN canonical_parcel.latitude IS NOT NULL
                 AND canonical_parcel.longitude IS NOT NULL
                    THEN 'canonical_parcel'
                WHEN avm_subject.latitude IS NOT NULL
                 AND avm_subject.longitude IS NOT NULL
                    THEN 'nj_avm_parcel'
                WHEN ss.source_system='nyc_nyctl_referee_sales'
                 AND p.latitude IS NOT NULL AND p.longitude IS NOT NULL
                    THEN 'nyc_planning_geosearch'
                WHEN p.latitude IS NULL
                 AND azr.raw_payload->'coordinates'->>'latitude' IS NOT NULL
                    THEN 'zillow'
                ELSE NULL
            END AS coordinate_source,
            ss.sheriff_number,
            ss.property_number AS bbl,
            CASE WHEN ss.source_system='nyc_nyctl_referee_sales'
                THEN 'Referee tax-lien auction'
                WHEN ss.source_system='nyc_kings_court_foreclosure_index'
                THEN 'Court foreclosure auction'
                WHEN ss.source_system='fl_hillsborough_published_foreclosure_notice'
                THEN 'Foreclosure auction (published notice)'
                WHEN ss.source_system='fl_columbia_clerk_foreclosure'
                THEN 'Foreclosure auction'
                WHEN ss.source_system='fl_palm_beach_sheriff_execution'
                THEN 'Sheriff execution sale'
                WHEN ss.source_system='fl_fdot_surplus_property'
                THEN 'FDOT surplus property'
                WHEN ss.source_system='fl_swfwmd_land_for_sale'
                THEN 'Government land for sale'
                WHEN ss.source_system='fl_us_treasury_real_property'
                THEN 'Federal seized-property auction'
                WHEN ss.source_system='il_tjsc_upcoming_sales'
                THEN 'Illinois judicial sale'
                WHEN ss.source_system='fl_realforeclose_clerk_sale'
                THEN 'Clerk foreclosure auction'
                WHEN ss.source_system='sc_master_in_equity_sale'
                THEN 'Master-in-Equity foreclosure sale'
                WHEN ss.source_system='co_realforeclose_public_trustee_sale'
                THEN 'Public Trustee foreclosure sale'
                WHEN ss.source_system='ct_court_foreclosure_sale'
                THEN 'Court foreclosure auction (committee sale)'
                WHEN ss.source_system='civilview_sheriff_sale' AND ss.state='TX'
                THEN 'Sheriff or constable sale'
                ELSE 'Sheriff sale' END AS sale_type,
            COALESCE(ss.docket_number, ss.court_case_number)
                AS court_case_number,
            ss.plaintiff,
            ss.defendant,
            CASE WHEN ss.source_system IN ('nyc_kings_court_foreclosure_index','fl_hillsborough_published_foreclosure_notice','fl_fdot_surplus_property','fl_swfwmd_land_for_sale','fl_us_treasury_real_property')
                THEN ss.description_text ELSE NULL END AS notice_details,
            ss.source_url AS foreclosure_source_url,
            CASE WHEN ss.source_system IN ('nyc_kings_court_foreclosure_index','fl_hillsborough_published_foreclosure_notice')
                AND ss.current_sale_date<CURRENT_DATE
                AND ss.current_status='scheduled_unverified'
                THEN 'date_passed_unverified'
                ELSE ss.current_status END AS current_status,
            ss.current_sale_date,
            COALESCE((SELECT JSONB_AGG(JSONB_BUILD_OBJECT(
                'status', h.status, 'raw_status', h.raw_status, 'event_date', COALESCE(h.sale_date, h.observed_at),
                'observed_at', h.observed_at, 'sale_date', h.sale_date, 'upset_price', h.upset_price
            ) ORDER BY COALESCE(h.sale_date, h.observed_at) DESC) FROM (
                SELECT status, raw_status, sale_date, upset_price, MAX(observed_at) AS observed_at
                FROM sheriff_sale_status_history
                WHERE sheriff_sale_id = ss.id
                GROUP BY status, raw_status, sale_date, upset_price
            ) h), '[]'::JSONB) AS status_history,
            azr.zestimate,
            CASE WHEN azr.zestimate IS NULL THEN COALESCE(azr.raw_payload, '{{}}'::JSONB)
                 ELSE JSONB_SET(COALESCE(azr.raw_payload, '{{}}'::JSONB), '{{zestimate}}', TO_JSONB(azr.zestimate), TRUE)
            END AS apify_data,
            ss.judgment_amount,
            ss.judgment_amount_as_of_date,
            ss.judgment_source_url,
            ss.starting_bid,
            ss.distress_start_date,
            ss.distress_start_year,
            ss.distress_start_basis,
            CASE WHEN status_dates.latest_scheduled_date IS NOT NULL
                       AND status_dates.earliest_status_date IS NOT NULL
                THEN GREATEST(status_dates.latest_scheduled_date - status_dates.earliest_status_date, 0)
                WHEN ss.distress_start_date IS NOT NULL
                THEN GREATEST(CURRENT_DATE - ss.distress_start_date, 0) END AS distress_duration_days,
            CASE WHEN ss.distress_start_date IS NULL AND ss.distress_start_year IS NOT NULL
                THEN GREATEST(CURRENT_DATE - make_date(ss.distress_start_year, 12, 31), 0) END AS distress_duration_min_days,
            CASE WHEN ss.distress_start_date IS NULL AND ss.distress_start_year IS NOT NULL
                THEN GREATEST(CURRENT_DATE - make_date(ss.distress_start_year, 1, 1), 0) END AS distress_duration_max_days,
            ss.notice_lien_amount,
            {UPSET_SQL} AS upset_price,
            {MINIMUM_BID_SQL} AS minimum_bid_amount,
            {MINIMUM_BID_BASIS_SQL} AS minimum_bid_basis,
            CASE WHEN ss.state='IL' THEN ss.upset_price END AS opening_bid,
            pv.estimated_value AS market_value,
            CASE WHEN pv.estimated_value IS NOT NULL AND ss.judgment_amount > 0
                THEN pv.estimated_value - ss.judgment_amount
            END AS avm_judgment_spread,
            CASE WHEN pv.estimated_value > 0 AND ss.judgment_amount > 0
                THEN (pv.estimated_value - ss.judgment_amount) / pv.estimated_value
            END AS avm_judgment_spread_percent,
            pv.low_value AS market_value_low,
            pv.high_value AS market_value_high,
            pv.provider AS valuation_provider,
            pv.confidence_score AS valuation_confidence,
            pv.retrieved_at AS valuation_retrieved_at,
            f.match_confidence AS parcel_match_confidence,
            CASE
                WHEN pv.id IS NOT NULL THEN 'VALUED'
                WHEN p.state = 'PA' AND p.county = 'Monroe' AND EXISTS (
                    SELECT 1 FROM pa_sheriff_sale_parcel_matches pm
                    WHERE pm.sheriff_sale_id = ss.id
                ) THEN 'MODEL_SCORING_REQUIRED'
                WHEN p.state = 'PA' AND p.county = 'Monroe'
                    THEN 'PARCEL_MATCH_REQUIRED'
                WHEN p.state <> 'NJ' OR p.county <> 'Monmouth'
                    THEN 'COUNTY_MODEL_UNAVAILABLE'
                WHEN f.property_id IS NULL AND EXISTS (
                    SELECT 1 FROM property_parcel_candidates ppc
                    WHERE ppc.property_id = p.id
                      AND ppc.review_status = 'PENDING'
                ) THEN 'PARCEL_MATCH_UNDER_REVIEW'
                WHEN f.property_id IS NULL THEN 'PARCEL_MATCH_REQUIRED'
                WHEN f.match_confidence < 90 THEN 'MANUAL_REVIEW_REQUIRED'
                WHEN TRIM(COALESCE(f.property_class,'')) <> '2'
                    THEN 'PROPERTY_TYPE_MODEL_UNAVAILABLE'
                ELSE 'MODEL_SCORING_REQUIRED'
            END AS valuation_status,
            CASE
                WHEN pv.id IS NOT NULL THEN NULL
                WHEN p.state = 'PA' AND p.county = 'Monroe' AND EXISTS (
                    SELECT 1 FROM pa_sheriff_sale_parcel_matches pm
                    WHERE pm.sheriff_sale_id = ss.id
                ) THEN 'Property has official KIZ details and is ready for experimental Monroe scoring.'
                WHEN p.state = 'PA' AND p.county = 'Monroe'
                    THEN 'The official KIZ crosswalk does not cover this parcel; no AVM estimate was fabricated.'
                WHEN p.state <> 'NJ' OR p.county <> 'Monmouth'
                    THEN 'A validated valuation model is not available for this county.'
                WHEN f.property_id IS NULL AND EXISTS (
                    SELECT 1 FROM property_parcel_candidates ppc
                    WHERE ppc.property_id = p.id
                      AND ppc.review_status = 'PENDING'
                ) THEN 'Parcel candidates require identity review.'
                WHEN f.property_id IS NULL
                    THEN 'A reliable parcel match has not been identified.'
                WHEN f.match_confidence < 90
                    THEN 'The parcel match requires manual review.'
                WHEN TRIM(COALESCE(f.property_class,'')) <> '2'
                    THEN 'The current local model is validated only for residential class-2 property.'
                WHEN COALESCE(p.square_feet, avm_subject.living_space) IS NULL
                    THEN 'Ready for lower-confidence model scoring with imputed living area.'
                ELSE 'Property is ready for local model scoring.'
            END AS valuation_pending_reason,
            CASE WHEN pv.estimated_value IS NOT NULL AND {MINIMUM_BID_SQL} IS NOT NULL
                THEN pv.estimated_value - {MINIMUM_BID_SQL}
            END AS gross_equity,
            CASE WHEN pv.estimated_value > 0 AND {MINIMUM_BID_SQL} IS NOT NULL
                THEN (pv.estimated_value - {MINIMUM_BID_SQL}) / pv.estimated_value
            END AS gross_equity_percent,
            sp.probability AS sale_probability,
            sp.feature_values AS sale_probability_features,
            sp.feature_explanations AS sale_probability_explanations,
            ra.risk_score,
            ra.risk_level,
            lrr.risk_score AS lien_risk_score,
            lrr.risk_level AS lien_risk_level,
            lrr.confidence_score AS lien_risk_confidence,
            lrr.known_exposure AS known_lien_exposure,
            lrr.calculated_at AS lien_risk_calculated_at,
            lc.total_lien_amount,
            COALESCE(lc.lien_record_count, 0) AS lien_record_count,
            COALESCE(lc.open_lien_count, 0) AS open_lien_count,
            COALESCE(lc.potentially_surviving_count, 0)
                AS potentially_surviving_lien_count,
            COALESCE(lc.manual_review_count, 0) AS lien_manual_review_count,
            COALESCE(lc.lien_items, '[]'::JSONB) AS lien_items
        FROM sheriff_sales AS ss
        JOIN properties AS p
            ON p.id = ss.property_id
        LEFT JOIN LATERAL (
            SELECT *
            FROM property_valuations
            WHERE property_id = p.id
              AND is_current = TRUE
            ORDER BY retrieved_at DESC
            LIMIT 1
        ) AS pv ON TRUE
        LEFT JOIN LATERAL (
            SELECT zestimate, raw_payload
            FROM apify_zillow_results
            WHERE property_id = p.id
              AND is_current = TRUE
              AND match_status <> 'invalid'
            ORDER BY retrieved_at DESC, id DESC
            LIMIT 1
        ) AS azr ON TRUE
        LEFT JOIN LATERAL (
            SELECT
                MAX(CASE WHEN LOWER(status) LIKE '%scheduled%' THEN COALESCE(sale_date, observed_at)::date END) AS latest_scheduled_date,
                MIN(COALESCE(sale_date, observed_at)::date) AS earliest_status_date
            FROM sheriff_sale_status_history
            WHERE sheriff_sale_id = ss.id
        ) AS status_dates ON TRUE
        LEFT JOIN property_avm_features AS f
            ON f.property_id = p.id
        LEFT JOIN LATERAL (
            SELECT
                cp.latitude,
                cp.longitude,
                cp.pams_pin,
                cp.block,
                cp.lot,
                cp.qualifier,
                snapshot.acreage,
                snapshot.year_built
            FROM sheriff_sale_parcels AS ssp
            JOIN parcels AS cp
                ON cp.id = ssp.parcel_id
            LEFT JOIN LATERAL (
                SELECT ps.acreage, ps.year_built
                FROM parcel_snapshots AS ps
                WHERE ps.parcel_id = cp.id
                ORDER BY ps.source_year DESC, ps.id DESC
                LIMIT 1
            ) AS snapshot ON TRUE
            WHERE ssp.sheriff_sale_id = ss.id
              AND ssp.match_status IN ('VERIFIED', 'MANUALLY_VERIFIED')
            ORDER BY
                CASE WHEN ssp.relationship = 'PRIMARY' THEN 0 ELSE 1 END,
                ssp.match_score DESC NULLS LAST
            LIMIT 1
        ) AS canonical_parcel ON TRUE
        LEFT JOIN LATERAL (
            SELECT living_space, latitude, longitude
            FROM nj_avm_training_sales
            WHERE municipality_code = f.municipality_code
              AND block = f.block
              AND lot = f.lot
              AND COALESCE(qualifier, '') = COALESCE(f.qualifier, '')
            ORDER BY deed_date DESC
            LIMIT 1
        ) AS avm_subject ON TRUE
        LEFT JOIN LATERAL (
            SELECT *
            FROM property_analyses
            WHERE sheriff_sale_id = ss.id
            ORDER BY calculated_at DESC
            LIMIT 1
        ) AS pa ON TRUE
        LEFT JOIN LATERAL (
            SELECT *
            FROM sale_predictions
            WHERE sheriff_sale_id = ss.id
              AND prediction_target = 'reaches_auction'
            ORDER BY predicted_at DESC
            LIMIT 1
        ) AS sp ON TRUE
        LEFT JOIN LATERAL (
            SELECT *
            FROM risk_assessments
            WHERE sheriff_sale_id = ss.id
            ORDER BY calculated_at DESC
            LIMIT 1
        ) AS ra ON TRUE
        LEFT JOIN LATERAL (
            SELECT *
            FROM lien_risk_reports
            WHERE property_id = p.id
            ORDER BY calculated_at DESC
            LIMIT 1
        ) AS lrr ON TRUE
        LEFT JOIN LATERAL (
            SELECT
                SUM(COALESCE(current_amount, original_amount)) FILTER (
                    WHERE status IN ('ACTIVE', 'POSSIBLY_ACTIVE', 'UNKNOWN')
                ) AS total_lien_amount,
                COUNT(*) AS lien_record_count,
                COUNT(*) FILTER (
                    WHERE status IN ('ACTIVE', 'POSSIBLY_ACTIVE', 'UNKNOWN')
                ) AS open_lien_count,
                COUNT(*) FILTER (
                    WHERE survival_classification IN (
                        'LIKELY_SURVIVES', 'MAY_SURVIVE'
                    )
                ) AS potentially_surviving_count,
                COUNT(*) FILTER (
                    WHERE requires_manual_review = TRUE
                ) AS manual_review_count,
                JSONB_AGG(
                    JSONB_BUILD_OBJECT(
                        'id', id,
                        'holder', COALESCE(
                            creditor_name,
                            CASE
                                WHEN lien_type IN ('MUNICIPAL_LIEN', 'PROPERTY_TAX')
                                    THEN 'Municipal/utility authority not specified'
                                ELSE 'Claimant not specified'
                            END
                        ),
                        'amount', COALESCE(current_amount, original_amount),
                        'type', lien_type,
                        'subtype', lien_subtype,
                        'status', status,
                        'position', CASE
                            WHEN is_foreclosing_lien = TRUE
                                OR priority_classification IN (
                                    'FORECLOSING_LIEN', 'FORECLOSING_CLAIM'
                                )
                                THEN 'PRIMARY_FORECLOSING'
                            WHEN priority_classification IN (
                                'SUPER_PRIORITY_LIEN', 'SUPER_PRIORITY_POSSIBLE',
                                'SENIOR_LIEN', 'POTENTIALLY_SURVIVING'
                            )
                                THEN 'POTENTIALLY_SENIOR'
                            WHEN priority_classification IN (
                                'JUNIOR_LIEN', 'LIKELY_EXTINGUISHED_LIEN'
                            )
                                THEN 'SECONDARY_JUNIOR'
                            ELSE 'PRIORITY_UNKNOWN'
                        END,
                        'position_confidence', priority_confidence
                    )
                    ORDER BY COALESCE(current_amount, original_amount)
                        DESC NULLS LAST, lien_type
                ) AS lien_items
            FROM property_liens
            WHERE property_id = p.id
        ) AS lc ON TRUE
        WHERE {where_clause}
        ORDER BY {order_by}
        LIMIT :limit
        OFFSET :offset
        """
    )

    spotlight_aggregates = (
        f", SUM({SPOTLIGHT_GROSS_EQUITY}) AS total_gross_equity"
        f", AVG({SPOTLIGHT_GROSS_EQUITY}) AS average_gross_equity"
        f", AVG({SPOTLIGHT_SCORE}) AS average_expected_equity"
        ", AVG(sp.probability) AS average_probability"
    ) if investor_spotlight else ""
    count_query = text(
        f"""
        SELECT COUNT(*) AS total{spotlight_aggregates}
        FROM sheriff_sales AS ss
        JOIN properties AS p
            ON p.id = ss.property_id
        LEFT JOIN LATERAL (
            SELECT *
            FROM property_valuations
            WHERE property_id = p.id
              AND is_current = TRUE
            ORDER BY retrieved_at DESC
            LIMIT 1
        ) AS pv ON TRUE
        LEFT JOIN LATERAL (
            SELECT zestimate
            FROM apify_zillow_results
            WHERE property_id = p.id
              AND is_current = TRUE
              AND match_status <> 'invalid'
            ORDER BY retrieved_at DESC, id DESC
            LIMIT 1
        ) AS azr ON TRUE
        LEFT JOIN LATERAL (
            SELECT *
            FROM property_analyses
            WHERE sheriff_sale_id = ss.id
            ORDER BY calculated_at DESC
            LIMIT 1
        ) AS pa ON TRUE
        LEFT JOIN LATERAL (
            SELECT *
            FROM risk_assessments
            WHERE sheriff_sale_id = ss.id
            ORDER BY calculated_at DESC
            LIMIT 1
        ) AS ra ON TRUE
        LEFT JOIN LATERAL (
            SELECT probability
            FROM sale_predictions
            WHERE sheriff_sale_id = ss.id
              AND prediction_target = 'reaches_auction'
            ORDER BY predicted_at DESC
            LIMIT 1
        ) AS sp ON TRUE
        WHERE {where_clause}
        """
    )

    with engine.connect() as connection:
        items = [
            dict(row)
            for row in connection.execute(
                query,
                parameters,
            ).mappings()
        ]

    for item in items:
        item["minimum_asking_amount"] = item.get("minimum_bid_amount")
        item["gross_equity"] = None
        item["gross_equity_percent"] = None
        zestimate = item.get("zestimate")
        opening_bid = item.get("opening_bid")
        try:
            zestimate_value = float(zestimate)
            if item.get("state") == "IL":
                basis_value = float(opening_bid) if opening_bid is not None else None
            else:
                basis_value = float(item["minimum_asking_amount"])
        except (TypeError, ValueError):
            zestimate_value = basis_value = None
        if zestimate_value is not None and basis_value is not None and zestimate_value > 0:
            item["gross_equity"] = zestimate_value - basis_value
            item["gross_equity_percent"] = (zestimate_value - basis_value) / zestimate_value
        probability = item.get("sale_probability")
        item["expected_equity"] = (
            float(item["gross_equity"]) * float(probability)
            if item.get("gross_equity") is not None and probability is not None else None
        )

    if sort in {"gross-equity", "gross-equity-percent"}:
        equity_field = "gross_equity" if sort == "gross-equity" else "gross_equity_percent"
        descending = sort_direction == "desc"

        def equity_sort_key(item):
            value = item.get(equity_field)
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                return (1, 0)
            return (0, -numeric if descending else numeric)

        items.sort(key=equity_sort_key)

    with engine.connect() as connection:
        counts = connection.execute(
            count_query,
            parameters,
        ).mappings().one()
    total = counts["total"]

    response = {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
    }
    if investor_spotlight:
        # Across every spotlight property matching the filters, not just this page.
        response["spotlight_summary"] = {
            "count": total,
            "total_gross_equity": float(counts["total_gross_equity"]) if counts["total_gross_equity"] is not None else None,
            "average_gross_equity": float(counts["average_gross_equity"]) if counts["average_gross_equity"] is not None else None,
            "average_expected_equity": float(counts["average_expected_equity"]) if counts["average_expected_equity"] is not None else None,
            "average_probability": float(counts["average_probability"]) if counts["average_probability"] is not None else None,
        }
    return response


@router.get("/export.xlsx", dependencies=[Depends(per_user("export", 20))])
def export_properties_xlsx(
    state: list[str] = Query(default=[]),
    county: list[str] = Query(default=[]),
    q: Optional[str] = Query(default=None, max_length=200),
    zip_code: Optional[str] = None,
    status: Optional[str] = None,
    status_contains: Optional[str] = Query(default=None, max_length=100),
    future_only: bool = False,
    min_equity: Optional[float] = None,
    sort: str = "sale-date",
    sort_direction: Literal["asc", "desc"] = "asc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=200),
    access: Access = Depends(require_access),
):
    result = list_properties(
        state=state, county=county, q=q, zip_code=zip_code, status=status,
        status_contains=status_contains, future_only=future_only,
        min_equity=min_equity, sort=sort, sort_direction=sort_direction,
        page=page, page_size=page_size, access=access,
    )
    rows = list(result["items"])

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sheriff properties"
    export_fields = list(EXPORT_FIELDS)
    if rows and all(row.get("state") == "IL" for row in rows):
        export_fields.insert(4, ("Opening bid", "opening_bid"))
    static_keys = [field for _, field in export_fields]
    apify_keys = APIFY_EXPORT_KEYS
    headers = [label for label, _ in export_fields] + apify_keys
    sheet.append(headers)
    for row in rows:
        values = [
            row.get(key.split(".", 1)[0]) if "." not in key
            else (row.get(key.split(".", 1)[0]) or {}).get(key.split(".", 1)[1])
            for key in static_keys
        ]
        apify_values = []
        for key in apify_keys:
            value = (row.get("apify_data") or {}).get(key)
            if key == "lotArea" and isinstance(value, dict) and isinstance(value.get("value"), (int, float)):
                unit = str(value.get("unit") or "").lower()
                acres = value["value"] if "acre" in unit else value["value"] / 43560
                value = f"{acres:,.2f} acres"
            elif isinstance(value, (dict, list)):
                value = readable_apify_value(value)
            apify_values.append(value)
        values.extend(apify_values)
        sheet.append([
            value if value is None or isinstance(value, (str, int, float, bool))
            else json.dumps(value, default=str)
            for value in values
        ])
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for column in sheet.columns:
        width = min(max(max(len(str(cell.value or "")) for cell in column) + 2, 10), 45)
        sheet.column_dimensions[column[0].column_letter].width = width
    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=sheriff-properties.xlsx"},
    )


@router.get("/facets/coverage")
def list_property_coverage(status_contains: Optional[str] = Query(default=None, max_length=100)):
    status_filter = f"AND strpos({EFFECTIVE_STATUS_SQL}, :status_contains) > 0" if status_contains and status_contains.strip() else ""
    query = text(
        f"""
        SELECT
            p.state,
            p.county,
            COUNT(DISTINCT p.id) AS property_count
        FROM sheriff_sales AS ss
        JOIN properties AS p
            ON p.id = ss.property_id
        WHERE ss.property_id IS NOT NULL
        {status_filter}
        GROUP BY p.state, p.county
        ORDER BY p.state, p.county
        """
    )

    with engine.connect() as connection:
        items = [
            dict(row)
            for row in connection.execute(
                query, {"status_contains": (status_contains or "").strip().lower()},
            ).mappings()
        ]

    return {"items": items}


@router.get("/facets/landing-summary")
def landing_summary(state: str = "NJ"):
    """Headline numbers for the landing page: upcoming scheduled sales, what
    is new this week, and the equity sitting behind the debt."""
    upcoming = (
        "ss.property_id IS NOT NULL AND ss.state = :state "
        "AND strpos(lower(ss.current_status), 'scheduled') > 0 "
        "AND ss.current_sale_date >= CURRENT_DATE"
    )
    zestimate_join = """
        LEFT JOIN LATERAL (
            SELECT zestimate FROM apify_zillow_results
            WHERE property_id = ss.property_id AND is_current = TRUE AND match_status <> 'invalid'
            ORDER BY retrieved_at DESC, id DESC LIMIT 1
        ) AS azr ON TRUE
    """
    equity = f"(azr.zestimate - {MINIMUM_BID_SQL})"
    with engine.connect() as connection:
        totals = connection.execute(text(f"""
            SELECT
                COUNT(*) AS upcoming_sales,
                COUNT(DISTINCT ss.county) AS counties,
                COUNT(*) FILTER (WHERE ss.current_sale_date < CURRENT_DATE + 7) AS next_7_days,
                COUNT(*) FILTER (WHERE ss.first_seen_at >= NOW() - INTERVAL '7 days') AS new_this_week,
                COUNT(*) FILTER (WHERE {equity} > 0) AS sales_with_equity,
                SUM({equity}) FILTER (WHERE {equity} > 0) AS equity_behind_debt,
                MAX(ss.last_scraped_at) AS last_updated
            FROM sheriff_sales AS ss
            {zestimate_join}
            WHERE {upcoming}
        """), {"state": state.upper()}).mappings().one()
        counties = connection.execute(text(f"""
            SELECT ss.county, COUNT(*) AS upcoming_sales,
                   SUM({equity}) FILTER (WHERE {equity} > 0) AS equity_behind_debt
            FROM sheriff_sales AS ss
            {zestimate_join}
            WHERE {upcoming}
            GROUP BY ss.county
            ORDER BY COUNT(*) DESC, ss.county
        """), {"state": state.upper()}).mappings().all()
    return {
        "state": state.upper(),
        "upcoming_sales": totals["upcoming_sales"],
        "counties": totals["counties"],
        "next_7_days": totals["next_7_days"],
        "new_this_week": totals["new_this_week"],
        "sales_with_equity": totals["sales_with_equity"],
        "equity_behind_debt": float(totals["equity_behind_debt"] or 0),
        "last_updated": totals["last_updated"],
        "county_counts": [
            {"county": row["county"], "upcoming_sales": row["upcoming_sales"],
             "equity_behind_debt": float(row["equity_behind_debt"] or 0)}
            for row in counties
        ],
    }


@router.get("/facets/state-summary")
def state_summary():
    """Scheduled sales and gross equity per state for the landing page. Uses the
    dashboard's own filter (status contains "scheduled") so a state's count
    matches what its dashboard shows."""
    equity = f"(azr.zestimate - {MINIMUM_BID_SQL})"
    with engine.connect() as connection:
        rows = connection.execute(text(f"""
            SELECT ss.state, COUNT(*) AS scheduled_sales, COUNT(DISTINCT ss.county) AS counties,
                   COUNT(*) FILTER (WHERE {equity} > 0) AS sales_with_equity,
                   SUM({equity}) FILTER (WHERE {equity} > 0) AS gross_equity,
                   MAX(ss.last_scraped_at) AS last_updated
            FROM sheriff_sales AS ss
            LEFT JOIN LATERAL (
                SELECT zestimate FROM apify_zillow_results
                WHERE property_id = ss.property_id AND is_current = TRUE AND match_status <> 'invalid'
                ORDER BY retrieved_at DESC, id DESC LIMIT 1
            ) AS azr ON TRUE
            WHERE ss.property_id IS NOT NULL AND strpos({EFFECTIVE_STATUS_SQL}, 'scheduled') > 0
            GROUP BY ss.state
            ORDER BY COUNT(*) DESC
        """)).mappings().all()
    return {"states": [
        {"state": row["state"], "scheduled_sales": row["scheduled_sales"], "counties": row["counties"],
         "sales_with_equity": row["sales_with_equity"], "gross_equity": float(row["gross_equity"] or 0),
         "last_updated": row["last_updated"]}
        for row in rows
    ]}


@router.get("/facets/nyc-auction-coverage")
def nyc_auction_coverage():
    boroughs = ("New York", "Bronx", "Kings", "Queens", "Richmond")
    with engine.connect() as connection:
        rows = connection.execute(text("""SELECT county,COUNT(*) AS count,MAX(last_scraped_at) AS checked_at
            FROM sheriff_sales WHERE state='NY'
              AND source_system IN ('nyc_nyctl_referee_sales','nyc_kings_court_foreclosure_index')
              AND current_status IN ('scheduled','scheduled_unverified')
              AND current_sale_date>=CURRENT_DATE
            GROUP BY county""")).mappings().all()
        checked = connection.execute(text("""SELECT MAX(completed_at) FROM scrape_runs
            WHERE job_name IN ('nyc_nyctl_referee_sales','nyc_kings_court_foreclosure_index')
              AND status='completed'""")).scalar()
    counts = {row["county"]: int(row["count"]) for row in rows}
    return {"source_type": "Court foreclosure and referee tax-lien auctions (not sheriff sales)",
            "source_url": "https://www.nycourts.gov/courts/2nd-judicial-district/kings-county-supreme-court-civil-term/foreclosure-sales",
            "last_checked_at": checked.isoformat() if checked else None,
            "boroughs": [{"county": county, "upcoming": counts.get(county, 0)} for county in boroughs],
            "coverage_note": "Includes address-indexed Kings court PDFs and NYCTL tax-lien referee listings, not a complete NYC foreclosure or Sheriff inventory. A calendar listing can be stayed or cancelled. Zero means no verified listing from these sources, not no auctions in the borough."}


NJ_ORTHO_EXPORT = (
    "https://maps.nj.gov/arcgis/rest/services/Basemap/Orthos_Natural_2020_NJ_WM/MapServer/export"
)
_aerial_cache: dict[str, bytes] = {}


@router.get("/{property_id}/aerial", dependencies=[Depends(require_property_access), Depends(per_user("photos", 1000))])
def get_aerial_photo(property_id: str):
    """Aerial photo centred on the property, from the NJ Office of GIS 2020
    natural-color orthoimagery (public state service). Cached in memory."""
    if property_id in _aerial_cache:
        return Response(content=_aerial_cache[property_id], media_type="image/jpeg",
                        headers={"Cache-Control": "private, max-age=604800"})
    with engine.connect() as connection:
        row = connection.execute(text("""
            SELECT p.state,
                   COALESCE(p.latitude, (azr.raw_payload->'coordinates'->>'latitude')::DOUBLE PRECISION) AS latitude,
                   COALESCE(p.longitude, (azr.raw_payload->'coordinates'->>'longitude')::DOUBLE PRECISION) AS longitude
            FROM properties p
            LEFT JOIN LATERAL (
                SELECT raw_payload FROM apify_zillow_results
                WHERE property_id = p.id AND is_current AND match_status <> 'invalid'
                ORDER BY retrieved_at DESC, id DESC LIMIT 1
            ) azr ON TRUE
            WHERE p.id::text = :id
        """), {"id": property_id}).mappings().first()
    if not row or row["state"] != "NJ" or row["latitude"] is None or row["longitude"] is None:
        raise HTTPException(status_code=404, detail="No NJ coordinates for this property")
    latitude, longitude = float(row["latitude"]), float(row["longitude"])
    # About 120 m x 90 m around the point, matching the 4:3 image.
    half_height = 45 / 111_320
    half_width = 60 / (111_320 * math.cos(math.radians(latitude)))
    params = {
        "bbox": f"{longitude - half_width},{latitude - half_height},{longitude + half_width},{latitude + half_height}",
        "bboxSR": "4326", "imageSR": "3857", "size": "640,480", "format": "jpg", "f": "image",
    }
    try:
        image = httpx.get(NJ_ORTHO_EXPORT, params=params, timeout=20,
                          headers={"User-Agent": "NJSheriffSalePro/1.0"})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="NJ imagery service unavailable") from exc
    if image.status_code != 200 or not image.headers.get("content-type", "").startswith("image/"):
        raise HTTPException(status_code=404, detail="No aerial image returned")
    if len(_aerial_cache) > 2000:
        _aerial_cache.clear()
    _aerial_cache[property_id] = image.content
    return Response(content=image.content, media_type="image/jpeg",
                    headers={"Cache-Control": "private, max-age=604800"})


STREET_VIEW_API = "https://maps.googleapis.com/maps/api/streetview"


@router.get("/{property_id}/street-view", dependencies=[Depends(require_property_access), Depends(per_user("photos", 1000))])
def get_street_view(property_id: str):
    """Street View photo for a property, fetched with our own Google key.

    The key stays server-side and the location comes from our own property
    record, so this is not an open proxy. Images are not stored; the browser
    may cache them for a day."""
    key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not key:
        raise HTTPException(status_code=404, detail="Street View is not configured")
    with engine.connect() as connection:
        address = connection.execute(
            text("SELECT normalized_address FROM properties WHERE id::text = :id"),
            {"id": property_id},
        ).scalar()
    if not address:
        raise HTTPException(status_code=404, detail="Property not found")
    location = " ".join(address.replace(",", " ").split())
    params = {"location": location, "source": "outdoor", "key": key}
    try:
        with httpx.Client(timeout=15) as client:
            # The metadata request is free and tells us whether imagery exists.
            metadata = client.get(f"{STREET_VIEW_API}/metadata", params=params).json()
            if metadata.get("status") != "OK":
                raise HTTPException(status_code=404, detail="No Street View imagery for this address")
            image = client.get(STREET_VIEW_API, params={**params, "size": "640x480", "fov": "80", "return_error_code": "true"})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Street View request failed") from exc
    if image.status_code != 200 or not image.headers.get("content-type", "").startswith("image/"):
        raise HTTPException(status_code=404, detail="No Street View image returned")
    return Response(
        content=image.content,
        media_type=image.headers["content-type"],
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.get("/{property_id}", dependencies=[Depends(require_property_access)])
def get_property(property_id: str):
    query = text(
        """
        SELECT
            p.*,
            ss.id AS sheriff_sale_id,
            ss.sheriff_number,
            CASE WHEN ss.source_system IN ('nyc_kings_court_foreclosure_index','fl_hillsborough_published_foreclosure_notice')
                AND ss.current_sale_date<CURRENT_DATE
                AND ss.current_status='scheduled_unverified'
                THEN 'date_passed_unverified'
                ELSE ss.current_status END AS current_status,
            ss.current_sale_date,
            COALESCE((SELECT JSONB_AGG(JSONB_BUILD_OBJECT(
                'status', h.status, 'raw_status', h.raw_status, 'event_date', COALESCE(h.sale_date, h.observed_at),
                'observed_at', h.observed_at, 'sale_date', h.sale_date, 'upset_price', h.upset_price
            ) ORDER BY COALESCE(h.sale_date, h.observed_at) DESC) FROM (
                SELECT status, raw_status, sale_date, upset_price, MAX(observed_at) AS observed_at
                FROM sheriff_sale_status_history
                WHERE sheriff_sale_id = ss.id
                GROUP BY status, raw_status, sale_date, upset_price
            ) h), '[]'::JSONB) AS status_history,
            ss.judgment_amount,
            ss.judgment_amount_as_of_date,
            ss.judgment_source_url,
            """ + UPSET_SQL + """ AS upset_price,
            """ + MINIMUM_BID_SQL + """ AS minimum_bid_amount,
            """ + MINIMUM_BID_BASIS_SQL + """ AS minimum_bid_basis,
            ss.plaintiff,
            ss.defendant,
            ss.source_url
        FROM properties AS p
        LEFT JOIN sheriff_sales AS ss
            ON ss.property_id = p.id
        WHERE p.id = :property_id
        ORDER BY ss.current_sale_date DESC
        LIMIT 1
        """
    )

    with engine.connect() as connection:
        record = connection.execute(
            query,
            {"property_id": property_id},
        ).mappings().first()

    if record is None:
        raise HTTPException(
            status_code=404,
            detail="Property not found",
        )

    return dict(record)
