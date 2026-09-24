import json
from io import BytesIO
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from pydantic import BaseModel
from sqlalchemy import text

from app.database.session import engine


router = APIRouter(
    prefix="/api/v1/properties",
    tags=["properties"],
)

EXPORT_FIELDS = [
    ("Distress source", "sale_type"),
    ("Gross equity", "gross_equity"), ("Gross equity %", "gross_equity_percent"),
    ("Estimated Market Value", "apify_data.zestimate"),
    ("Minimum asking amount", "minimum_asking_amount"),
    ("Description", "apify_data.description"),
    ("Address", "normalized_address"), ("Street address", "street_address"),
    ("City", "city"), ("County", "county"), ("State", "state"), ("ZIP", "zip_code"),
    ("Court case", "court_case_number"), ("Parcel / tax ID", "bbl"), ("Status", "current_status"),
    ("Sale date", "current_sale_date"), ("Plaintiff", "plaintiff"), ("Defendant", "defendant"),
    ("Time in distress", "distress_duration_days"),
    ("Notice lien amount", "notice_lien_amount"),
    ("Probability to auction", "sale_probability"), ("Lien risk score", "lien_risk_score"),
    ("Lien risk level", "lien_risk_level"), ("Lien risk confidence", "lien_risk_confidence"),
    ("Total lien amount", "total_lien_amount"),
    ("Valuation retrieved", "valuation_retrieved_at"), ("Lien risk calculated", "lien_risk_calculated_at"),
]
APIFY_EXPORT_KEYS = [
    "homeType", "lastSoldPrice", "bedrooms", "bathrooms", "livingArea", "yearBuilt",
    "daysOnZillow", "pageViewCount", "favoriteCount", "rentZestimate",
    "lotArea", "pricePerSquareFoot", "taxAssessedValue", "onMarketDate", "taxAnnualAmount",
    "parking", "dateSold", "priceChange", "priceChangedAt", "monthlyHoaFee",
    "hoa", "propertyTaxRate", "listingMortgageRates",
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

@router.get("/parcel-review/candidates")
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

@router.post("/{property_id}/parcel-review/approve")
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


@router.get("")
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
    sort: str = "sale-date",
    sort_direction: Literal["asc", "desc"] = "asc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    offset = (page - 1) * page_size

    conditions = ["ss.property_id IS NOT NULL"]
    parameters = {
        "limit": page_size,
        "offset": offset,
    }

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

    effective_status = "LOWER(CASE WHEN ss.source_system IN ('nyc_kings_court_foreclosure_index','fl_hillsborough_published_foreclosure_notice') AND ss.current_sale_date<CURRENT_DATE AND ss.current_status='scheduled_unverified' THEN 'date_passed_unverified' ELSE ss.current_status END)"
    if status:
        conditions.append(f"{effective_status} = :status")
        parameters["status"] = status.lower()

    if status_contains and status_contains.strip():
        conditions.append(f"strpos({effective_status}, :status_contains) > 0")
        parameters["status_contains"] = status_contains.strip().lower()

    if future_only:
        conditions.append("ss.current_sale_date >= CURRENT_DATE")

    if min_equity is not None:
        conditions.append("azr.zestimate - CASE WHEN ss.state='IL' THEN ss.upset_price ELSE GREATEST(ss.estimated_upset_price, ss.alternate_upset_price, ss.upset_price) END >= :min_equity")
        parameters["min_equity"] = min_equity

    if max_risk is not None:
        conditions.append("ra.risk_score <= :max_risk")
        parameters["max_risk"] = max_risk

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
        "opening-bid": "CASE WHEN ss.state='IL' THEN ss.upset_price END",
        "judgment-amount": "ss.judgment_amount", "starting-bid": "ss.starting_bid", "gross-equity": "gross_equity",
        "distress-duration": "COALESCE(ss.distress_start_date, make_date(ss.distress_start_year, 1, 1))",
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
        "lien-risk-calculated": "lien_risk_calculated_at", "foreclosure-source": "ss.source_url",
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
            COALESCE(canonical_parcel.latitude, avm_subject.latitude, p.latitude)
                AS latitude,
            COALESCE(canonical_parcel.longitude, avm_subject.longitude, p.longitude)
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
            CASE WHEN ss.distress_start_date IS NOT NULL
                THEN GREATEST(CURRENT_DATE - ss.distress_start_date, 0) END AS distress_duration_days,
            CASE WHEN ss.distress_start_date IS NULL AND ss.distress_start_year IS NOT NULL
                THEN GREATEST(CURRENT_DATE - make_date(ss.distress_start_year, 12, 31), 0) END AS distress_duration_min_days,
            CASE WHEN ss.distress_start_date IS NULL AND ss.distress_start_year IS NOT NULL
                THEN GREATEST(CURRENT_DATE - make_date(ss.distress_start_year, 1, 1), 0) END AS distress_duration_max_days,
            ss.notice_lien_amount,
            GREATEST(
                ss.estimated_upset_price,
                ss.alternate_upset_price,
                ss.upset_price
            ) AS upset_price,
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
            CASE
                WHEN pv.estimated_value IS NOT NULL
                 AND GREATEST(
                    ss.estimated_upset_price,
                    ss.alternate_upset_price,
                    ss.upset_price
                 ) IS NOT NULL
                THEN pv.estimated_value - GREATEST(
                    ss.estimated_upset_price,
                    ss.alternate_upset_price,
                    ss.upset_price
                )
            END AS gross_equity,
            CASE
                WHEN pv.estimated_value > 0
                 AND GREATEST(
                    ss.estimated_upset_price,
                    ss.alternate_upset_price,
                    ss.upset_price
                 ) IS NOT NULL
                THEN (
                    pv.estimated_value - GREATEST(
                        ss.estimated_upset_price,
                        ss.alternate_upset_price,
                        ss.upset_price
                    )
                ) / pv.estimated_value
            END AS gross_equity_percent,
            sp.probability AS sale_probability,
            sp.feature_values AS sale_probability_features,
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
            ORDER BY retrieved_at DESC, id DESC
            LIMIT 1
        ) AS azr ON TRUE
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

    count_query = text(
        f"""
        SELECT COUNT(*)
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
        item["minimum_asking_amount"] = item.get("upset_price") if item.get("upset_price") is not None else item.get("judgment_amount")
        item["gross_equity"] = None
        item["gross_equity_percent"] = None
        zestimate = item.get("zestimate")
        upset_price = item.get("upset_price")
        judgment = item.get("judgment_amount")
        opening_bid = item.get("opening_bid")
        try:
            zestimate_value = float(zestimate)
            if item.get("state") == "IL":
                basis_value = float(opening_bid) if opening_bid is not None else None
            else:
                basis_value = float(upset_price) if upset_price is not None else float(judgment)
        except (TypeError, ValueError):
            zestimate_value = basis_value = None
        if zestimate_value is not None and basis_value is not None and zestimate_value > 0:
            item["gross_equity"] = zestimate_value - basis_value
            item["gross_equity_percent"] = (zestimate_value - basis_value) / zestimate_value

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
        total = connection.execute(
            count_query,
            parameters,
        ).scalar_one()

    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.get("/export.xlsx")
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
):
    result = list_properties(
        state=state, county=county, q=q, zip_code=zip_code, status=status,
        status_contains=status_contains, future_only=future_only,
        min_equity=min_equity, sort=sort, sort_direction=sort_direction,
        page=page, page_size=page_size,
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
def list_property_coverage():
    query = text(
        """
        SELECT
            p.state,
            p.county,
            COUNT(DISTINCT p.id) AS property_count
        FROM sheriff_sales AS ss
        JOIN properties AS p
            ON p.id = ss.property_id
        WHERE ss.property_id IS NOT NULL
        GROUP BY p.state, p.county
        ORDER BY p.state, p.county
        """
    )

    with engine.connect() as connection:
        items = [
            dict(row)
            for row in connection.execute(query).mappings()
        ]

    return {"items": items}


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


@router.get("/{property_id}")
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
            ss.judgment_amount,
            ss.judgment_amount_as_of_date,
            ss.judgment_source_url,
            GREATEST(
                ss.estimated_upset_price,
                ss.alternate_upset_price,
                ss.upset_price
            ) AS upset_price,
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
