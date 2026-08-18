from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from app.database.session import engine
from app.liens.models import LienRecord, SourceCoverage, SourceStatus
from app.liens.risk import calculate_lien_risk
from app.liens.sources import parse_civilview_disclosures


router = APIRouter(prefix="/api/v1/properties", tags=["liens"])

PUBLIC_SOURCE_COVERAGE = (
    ("CivilView sale notice", "SHERIFF_NOTICE", SourceStatus.SUCCESS, None),
    ("Monmouth County land records", "COUNTY_LAND_RECORDS", SourceStatus.MANUAL_REVIEW_REQUIRED,
     "The county states that title searches must be performed in person."),
    ("New Jersey judgments", "JUDGMENTS", SourceStatus.NOT_CONFIGURED,
     "State judgment search adapter is not configured."),
    ("Municipal tax and utility", "MUNICIPAL", SourceStatus.MANUAL_REVIEW_REQUIRED,
     "Obtain a current certified municipal search or collector verification."),
    ("HOA/condominium records", "HOA", SourceStatus.MANUAL_REVIEW_REQUIRED,
     "Association identity and balances are not reliably available from one public source."),
)

CATEGORY_COVERAGE = (
    ("MORTGAGE", "Monmouth County OPRS", "MANUAL_REVIEW_REQUIRED",
     "County portal automation is unavailable; search by block/lot and owner."),
    ("LIS_PENDENS", "Monmouth County OPRS", "MANUAL_REVIEW_REQUIRED",
     "County portal automation is unavailable; foreclosure case is known from CivilView."),
    ("CONSTRUCTION_LIEN", "Monmouth County OPRS", "MANUAL_REVIEW_REQUIRED",
     "County land-record search is required."),
    ("HOA_LIEN", "County records / association", "MANUAL_REVIEW_REQUIRED",
     "No complete statewide public HOA balance source exists."),
    ("CIVIL_JUDGMENT", "NJ Courts Judgment Lien Public Access", "SOURCE_UNAVAILABLE",
     "Portal blocks automation; use an authorized search or manual import."),
    ("CHILD_SUPPORT", "NJ Courts Judgment Lien Public Access", "SOURCE_UNAVAILABLE",
     "Portal blocks automation; use an authorized search or manual import."),
    ("TAX_LIEN", "NJ Courts / County OPRS", "MANUAL_REVIEW_REQUIRED",
     "Search state judgment and county IRS lien indexes."),
    ("UNPAID_PROPERTY_TAX", "Municipal tax collector", "MANUAL_REVIEW_REQUIRED",
     "A current collector balance is required; MOD-IV is assessment data only."),
    ("WATER_SEWER", "CivilView / municipal collector", "NOT_CHECKED",
     "CivilView may contain a disclosure; collector verification is still required."),
    ("TAX_SALE_CERTIFICATE", "Municipal tax collector", "MANUAL_REVIEW_REQUIRED",
     "A municipal tax-sale or redemption search is required."),
    ("UCC_1", "NJ DORES UCC Search", "MANUAL_REVIEW_REQUIRED",
     "Search by exact resolved debtor/entity name; address-only matching is unsafe."),
)


def _json_default(value: object) -> str:
    if isinstance(value, (datetime, Decimal)):
        return str(value)
    raise TypeError(f"Cannot serialize {type(value)}")


def _coverage() -> list[SourceCoverage]:
    return [
        SourceCoverage(
            source_name=name,
            source_type=source_type,
            status=status,
            message=message,
        )
        for name, source_type, status, message in PUBLIC_SOURCE_COVERAGE
    ]


@router.post("/{property_id}/liens/refresh")
def refresh_liens(property_id: str):
    query = text("""
        SELECT p.id::text AS property_id, ss.id::text AS sheriff_sale_id,
               ss.plaintiff, ss.defendant, ss.court_case_number,
               ss.source_url, ss.description_text
        FROM properties p
        JOIN sheriff_sales ss ON ss.property_id = p.id
        WHERE p.id = CAST(:property_id AS UUID)
        ORDER BY ss.current_sale_date DESC NULLS LAST
        LIMIT 1
    """)
    with engine.begin() as connection:
        sale = connection.execute(query, {"property_id": property_id}).mappings().first()
        if sale is None:
            raise HTTPException(status_code=404, detail="Property or sheriff sale not found")
        if not sale["description_text"]:
            raise HTTPException(
                status_code=409,
                detail="No saved CivilView description is available for automated screening",
            )

        records = parse_civilview_disclosures(
            sale["description_text"],
            source_url=sale["source_url"],
            plaintiff=sale["plaintiff"],
            defendant=sale["defendant"],
            case_number=sale["court_case_number"],
        )
        payload = {
            "description_text": sale["description_text"],
            "parsed_records": [item.model_dump(mode="json") for item in records],
        }
        payload_json = json.dumps(payload, default=_json_default)
        digest = hashlib.sha256(payload_json.encode()).hexdigest()
        raw_id = connection.execute(text("""
            INSERT INTO raw_lien_records (
                property_id, source_name, source_record_id, source_url,
                raw_payload, content_hash, parser_version
            ) VALUES (
                CAST(:property_id AS UUID), 'CIVILVIEW_DISCLOSURE', :source_record_id,
                :source_url, CAST(:payload AS JSONB), :content_hash, 'civilview-liens-v1'
            )
            ON CONFLICT (property_id, source_name, content_hash)
            DO UPDATE SET retrieved_at = NOW()
            RETURNING id::text
        """), {
            "property_id": property_id,
            "source_record_id": sale["sheriff_sale_id"],
            "source_url": sale["source_url"],
            "payload": payload_json,
            "content_hash": digest,
        }).scalar_one()

        connection.execute(text("""
            DELETE FROM property_liens
            WHERE property_id = CAST(:property_id AS UUID)
              AND source_name = 'CIVILVIEW_DISCLOSURE'
        """), {"property_id": property_id})
        for item in records:
            data = item.model_dump()
            connection.execute(text("""
                INSERT INTO property_liens (
                    property_id, sheriff_sale_id, raw_record_id, lien_type, lien_subtype,
                    status, creditor_name, debtor_name, original_amount, current_amount,
                    recording_date, effective_date, instrument_number, docket_number,
                    case_number, is_foreclosing_lien, match_confidence, match_reason,
                    priority_classification, priority_confidence, survival_classification,
                    survival_confidence, requires_manual_review, source_name, source_url,
                    source_effective_at
                ) VALUES (
                    CAST(:property_id AS UUID), CAST(:sheriff_sale_id AS UUID), CAST(:raw_id AS UUID),
                    :lien_type, :lien_subtype, :status, :creditor_name, :debtor_name,
                    :original_amount, :current_amount, :recording_date, :effective_date,
                    :instrument_number, :docket_number, :case_number, :is_foreclosing_lien,
                    :match_confidence, :match_reason, :priority_classification,
                    :priority_confidence, :survival_classification, :survival_confidence,
                    :requires_manual_review, :source_name, :source_url, :source_effective_at
                )
            """), {
                **data,
                "status": item.status.value,
                "property_id": property_id,
                "sheriff_sale_id": sale["sheriff_sale_id"],
                "raw_id": raw_id,
            })

        report = calculate_lien_risk(property_id, records, _coverage())
        connection.execute(text("""
            INSERT INTO lien_risk_reports (
                property_id, sheriff_sale_id, risk_score, risk_level,
                confidence_score, known_exposure, components, flags,
                source_coverage, calculation_version, calculated_at
            ) VALUES (
                CAST(:property_id AS UUID), CAST(:sheriff_sale_id AS UUID),
                :risk_score, :risk_level, :confidence_score, :known_exposure,
                CAST(:components AS JSONB), CAST(:flags AS JSONB),
                CAST(:coverage AS JSONB), :version, :calculated_at
            )
        """), {
            "property_id": property_id,
            "sheriff_sale_id": sale["sheriff_sale_id"],
            "risk_score": report.risk_score,
            "risk_level": report.risk_level,
            "confidence_score": report.confidence_score,
            "known_exposure": report.known_exposure,
            "components": json.dumps(report.components),
            "flags": json.dumps([item.model_dump(mode="json") for item in report.flags]),
            "coverage": json.dumps([item.model_dump(mode="json") for item in report.source_coverage]),
            "version": report.calculation_version,
            "calculated_at": report.calculated_at,
        })

        for category, source_name, default_status, message in CATEGORY_COVERAGE:
            matching = [
                item for item in records
                if (
                    category == "WATER_SEWER"
                    and item.lien_subtype in {"SEWER_CHARGE", "WATER_CHARGE_UNKNOWN"}
                ) or (
                    category == "UNPAID_PROPERTY_TAX"
                    and item.lien_type == "PROPERTY_TAX"
                )
            ]
            status = "PARTIAL" if matching else default_status
            known_amounts = [
                amount
                for item in matching
                if (amount := item.current_amount or item.original_amount) is not None
            ]
            quantified = sum(known_amounts, Decimal("0")) if known_amounts else None
            connection.execute(text("""
                INSERT INTO lien_category_coverage (
                    property_id, category, source_name, status, record_count,
                    quantified_amount, source_url, message, checked_at, updated_at
                ) VALUES (
                    CAST(:property_id AS UUID), :category, :source_name, :status,
                    :record_count, :quantified_amount, :source_url, :message, NOW(), NOW()
                )
                ON CONFLICT (property_id, category, source_name)
                DO UPDATE SET status = EXCLUDED.status,
                              record_count = EXCLUDED.record_count,
                              quantified_amount = EXCLUDED.quantified_amount,
                              source_url = EXCLUDED.source_url,
                              message = EXCLUDED.message,
                              checked_at = EXCLUDED.checked_at,
                              updated_at = NOW()
            """), {
                "property_id": property_id,
                "category": category,
                "source_name": source_name,
                "status": status,
                "record_count": len(matching),
                "quantified_amount": quantified,
                "source_url": sale["source_url"] if matching else None,
                "message": (
                    f"{len(matching)} disclosure(s) found in CivilView; current source verification remains required."
                    if matching else message
                ),
            })

    return {
        "status": "COMPLETED",
        "records_found": len(records),
        "risk_score": report.risk_score,
        "risk_level": report.risk_level,
        "confidence_score": report.confidence_score,
    }


@router.get("/{property_id}/liens")
def get_liens(property_id: str):
    with engine.connect() as connection:
        rows = connection.execute(text("""
            SELECT id::text, lien_type, lien_subtype, status, creditor_name,
                   debtor_name, original_amount, current_amount, recording_date,
                   effective_date, instrument_number, docket_number, case_number,
                   is_foreclosing_lien, match_confidence, match_reason,
                   priority_classification, priority_confidence,
                   survival_classification, survival_confidence,
                   requires_manual_review, source_name, source_url, source_effective_at
            FROM property_liens
            WHERE property_id = CAST(:property_id AS UUID)
            ORDER BY requires_manual_review DESC, current_amount DESC NULLS LAST
        """), {"property_id": property_id}).mappings().all()
    return {"items": [dict(row) for row in rows]}


@router.get("/{property_id}/lien-risk")
def get_lien_risk(property_id: str):
    with engine.connect() as connection:
        exists = connection.execute(text(
            "SELECT 1 FROM properties WHERE id = CAST(:property_id AS UUID)"
        ), {"property_id": property_id}).first()
        if exists is None:
            raise HTTPException(status_code=404, detail="Property not found")
        rows = connection.execute(text("""
            SELECT id::text, lien_type, lien_subtype, status, creditor_name,
                   debtor_name, original_amount, current_amount, recording_date,
                   effective_date, instrument_number, docket_number, case_number,
                   is_foreclosing_lien, match_confidence, match_reason,
                   priority_classification, priority_confidence,
                   survival_classification, survival_confidence,
                   requires_manual_review, source_name, source_url, source_effective_at
            FROM property_liens WHERE property_id = CAST(:property_id AS UUID)
        """), {"property_id": property_id}).mappings().all()
    report = calculate_lien_risk(
        property_id,
        [LienRecord.model_validate(dict(row)) for row in rows],
        _coverage(),
    )
    return report


@router.get("/{property_id}/lien-coverage")
def get_lien_coverage(property_id: str):
    with engine.connect() as connection:
        rows = connection.execute(text("""
            SELECT category, source_name, status, record_count,
                   quantified_amount, source_url, message, checked_at,
                   source_effective_at
            FROM lien_category_coverage
            WHERE property_id = CAST(:property_id AS UUID)
            ORDER BY category, source_name
        """), {"property_id": property_id}).mappings().all()
    return {"items": [dict(row) for row in rows]}
