from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text

from app.database.session import engine


router = APIRouter(
    prefix="/api/v1/properties",
    tags=["properties"],
)

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
    zip_code: Optional[str] = None,
    status: Optional[str] = None,
    future_only: bool = False,
    min_equity: Optional[float] = None,
    max_risk: Optional[int] = None,
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
        conditions.append("p.county = ANY(:counties)")
        parameters["counties"] = county

    if zip_code:
        conditions.append("p.zip_code = :zip_code")
        parameters["zip_code"] = zip_code

    if status:
        conditions.append("ss.current_status = :status")
        parameters["status"] = status

    if future_only:
        conditions.append("ss.current_sale_date >= CURRENT_DATE")

    if min_equity is not None:
        conditions.append(
            "pv.estimated_value - GREATEST("
            "ss.estimated_upset_price, "
            "ss.alternate_upset_price, ss.upset_price"
            ") >= :min_equity"
        )
        parameters["min_equity"] = min_equity

    if max_risk is not None:
        conditions.append("ra.risk_score <= :max_risk")
        parameters["max_risk"] = max_risk

    where_clause = " AND ".join(conditions)

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
            ss.sheriff_number,
            COALESCE(ss.docket_number, ss.court_case_number)
                AS court_case_number,
            ss.plaintiff,
            ss.defendant,
            ss.source_url AS foreclosure_source_url,
            ss.current_status,
            ss.current_sale_date,
            ss.judgment_amount,
            GREATEST(
                ss.estimated_upset_price,
                ss.alternate_upset_price,
                ss.upset_price
            ) AS upset_price,
            pv.estimated_value AS market_value,
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
        LEFT JOIN property_avm_features AS f
            ON f.property_id = p.id
        LEFT JOIN LATERAL (
            SELECT living_space
            FROM nj_avm_training_sales
            WHERE municipality_code = f.municipality_code
              AND block = f.block
              AND lot = f.lot
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
        ORDER BY ss.current_sale_date, p.normalized_address
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


@router.get("/{property_id}")
def get_property(property_id: str):
    query = text(
        """
        SELECT
            p.*,
            ss.id AS sheriff_sale_id,
            ss.sheriff_number,
            ss.current_status,
            ss.current_sale_date,
            ss.judgment_amount,
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
