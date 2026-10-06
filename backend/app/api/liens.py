from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import text

from app.auth import require_developer
from app.database.session import engine
from app.liens.models import LienRecord, SourceCoverage, SourceStatus
from app.liens.risk import calculate_lien_risk
from app.liens.summary import build_preliminary_summary
from app.liens.source_registry import county_capabilities, municipal_capabilities
from app.liens.monmouth import MONMOUTH_OPRS_URL, PARSER_VERSION, MonmouthOPRSAdapter, SOURCE_NAME
from app.liens.sources import PropertyIdentity
from app.liens.sources import parse_civilview_disclosures
from app.liens.title_search import get_professional_title_search


router = APIRouter(prefix="/api/v1/properties", tags=["liens"])
jobs_router = APIRouter(prefix="/api/v1/lien-jobs", tags=["lien-jobs"])

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


def _coverage(overrides: dict[str, SourceCoverage] | None = None) -> list[SourceCoverage]:
    items = [
        SourceCoverage(
            source_name=name,
            source_type=source_type,
            status=status,
            message=message,
        )
        for name, source_type, status, message in PUBLIC_SOURCE_COVERAGE
    ]
    for index, item in enumerate(items):
        if overrides and item.source_type in overrides:
            items[index] = overrides[item.source_type]
    return items


def _monmouth_identity(sale: dict) -> PropertyIdentity:
    owners = tuple(
        part.strip()
        for part in (sale.get("defendant") or "").replace(";", ",").split(",")
        if part.strip() and part.strip().lower() not in {"et al", "et al."}
    )
    return PropertyIdentity(
        property_id=str(sale["property_id"]),
        address=sale.get("normalized_address") or "",
        county=sale.get("county") or "Monmouth",
        municipality=sale.get("municipality") or sale.get("city"),
        block=sale.get("block"),
        lot=sale.get("lot"),
        qualifier=sale.get("qualifier"),
        pams_pin=sale.get("pams_pin"),
        current_owners=owners,
    )


def _refresh_monmouth(connection, sale: dict) -> dict:
    identity = _monmouth_identity(sale)
    checked_at = datetime.now(timezone.utc)
    run_id = connection.execute(text("""
        INSERT INTO lien_source_runs(property_id, source_name, source_type, status, source_url, query)
        VALUES(CAST(:property_id AS UUID), :source_name, 'COUNTY_LAND_RECORDS', 'MANUAL_REVIEW_REQUIRED', :source_url, CAST(:query AS JSONB))
        RETURNING id::text
    """), {"property_id": sale["property_id"], "source_name": SOURCE_NAME,
            "source_url": MONMOUTH_OPRS_URL,
            "query": json.dumps({"block": identity.block, "lot": identity.lot, "municipality": identity.municipality,
                                  "owner": list(identity.current_owners)})}).scalar_one()
    try:
        liens, raw_records, relationships = asyncio.run(MonmouthOPRSAdapter().search_property_with_raw(identity))
    except Exception as exc:
        message = str(exc) or "The public county source could not be queried."
        connection.execute(text("""
            UPDATE lien_source_runs SET status='MANUAL_REVIEW_REQUIRED', error_message=:message,
                checked_at=:checked_at WHERE id=CAST(:run_id AS UUID)
        """), {"run_id": run_id, "message": message, "checked_at": checked_at})
        return {
            "status": "MANUAL_REVIEW_REQUIRED", "source": SOURCE_NAME, "source_url": MONMOUTH_OPRS_URL,
            "reason": message, "owner": list(identity.current_owners), "property_address": identity.address,
            "block": identity.block, "lot": identity.lot, "pams_pin": identity.pams_pin,
            "recommended_search_terms": [identity.block or "", identity.lot or "", *identity.current_owners],
        }

    raw_ids: dict[str, str] = {}
    for raw in raw_records:
        query_json = json.dumps({"block": identity.block, "lot": identity.lot, "municipality": identity.municipality,
                                 "owner": list(identity.current_owners)})
        raw_id = connection.execute(text("""
            INSERT INTO raw_lien_records(
                property_id, source_run_id, source_name, source_type, source_record_id, source_url,
                search_type, search_query, raw_payload, content_hash, retrieved_at, parser_version,
                ingestion_status
            ) VALUES(CAST(:property_id AS UUID), CAST(:run_id AS UUID), :source_name, 'COUNTY_LAND_RECORDS',
                :source_record_id, :source_url, 'BLOCK_LOT_OR_OWNER', CAST(:query AS JSONB),
                CAST(:payload AS JSONB), :content_hash, :retrieved_at, :parser_version, 'INGESTED')
            ON CONFLICT(property_id, source_name, content_hash)
            DO UPDATE SET retrieved_at=EXCLUDED.retrieved_at, source_run_id=EXCLUDED.source_run_id
            RETURNING id::text
        """), {"property_id": sale["property_id"], "run_id": run_id, "source_name": SOURCE_NAME,
                "source_record_id": raw.source_record_id, "source_url": raw.source_url,
                "query": query_json,
                "payload": json.dumps(raw.raw_data), "content_hash": raw.content_hash,
                "retrieved_at": raw.retrieved_at, "parser_version": PARSER_VERSION}).scalar_one()
        raw_ids[raw.source_record_id] = raw_id
        connection.execute(text("""
            INSERT INTO raw_public_records(
                property_id, source_name, source_type, source_url, source_record_id,
                search_type, search_query, raw_data, retrieved_at, ingestion_status,
                parser_version, content_hash
            ) VALUES(CAST(:property_id AS UUID), :source_name, 'COUNTY_LAND_RECORDS', :source_url,
                :source_record_id, 'BLOCK_LOT_OR_OWNER', CAST(:query AS JSONB), CAST(:raw_data AS JSONB),
                :retrieved_at, 'INGESTED', :parser_version, :content_hash)
            ON CONFLICT(property_id, source_name, content_hash) DO UPDATE SET retrieved_at=EXCLUDED.retrieved_at
        """), {"property_id": sale["property_id"], "source_name": SOURCE_NAME, "source_url": raw.source_url,
                "source_record_id": raw.source_record_id, "query": query_json, "raw_data": json.dumps(raw.raw_data),
                "retrieved_at": raw.retrieved_at, "parser_version": PARSER_VERSION, "content_hash": raw.content_hash})

    connection.execute(text("DELETE FROM lien_relationships WHERE parent_lien_id IN (SELECT id FROM property_liens WHERE property_id=CAST(:property_id AS UUID) AND source_name=:source_name) OR child_lien_id IN (SELECT id FROM property_liens WHERE property_id=CAST(:property_id AS UUID) AND source_name=:source_name)"), {"property_id": sale["property_id"], "source_name": SOURCE_NAME})
    connection.execute(text("DELETE FROM property_liens WHERE property_id=CAST(:property_id AS UUID) AND source_name=:source_name"), {"property_id": sale["property_id"], "source_name": SOURCE_NAME})
    lien_ids: list[tuple[str, object]] = []
    for lien in liens:
        values = lien.model_dump()
        lien_id = connection.execute(text("""
            INSERT INTO property_liens(
                property_id, sheriff_sale_id, raw_record_id, source_record_id, lien_type, lien_subtype, status,
                creditor_name, debtor_name, original_amount, current_amount, recording_date, instrument_number,
                county, municipality, block, lot, qualifier, pams_pin, property_address, matching_method,
                match_confidence, match_reason, priority_classification, priority_confidence,
                survival_classification, survival_confidence, requires_manual_review, source_name, source_url,
                source_effective_at
            ) VALUES(CAST(:property_id AS UUID), CAST(:sheriff_sale_id AS UUID), CAST(:raw_id AS UUID),
                :source_record_id, :lien_type, :lien_subtype, :status, :creditor_name, :debtor_name,
                :original_amount, :current_amount, :recording_date, :instrument_number, :county, :municipality,
                :block, :lot, :qualifier, :pams_pin, :property_address, :matching_method, :match_confidence,
                :match_reason, :priority_classification, :priority_confidence, :survival_classification,
                :survival_confidence, :requires_manual_review, :source_name, :source_url, :source_effective_at)
            RETURNING id::text
        """), {**values, "property_id": sale["property_id"], "sheriff_sale_id": sale["sheriff_sale_id"],
                "raw_id": raw_ids.get(lien.instrument_number), "source_record_id": lien.instrument_number,
                "status": lien.status.value, "county": sale.get("county"), "municipality": identity.municipality,
                "block": identity.block, "lot": identity.lot, "qualifier": identity.qualifier,
                "pams_pin": identity.pams_pin, "property_address": identity.address,
                "matching_method": "PUBLIC_RECORD_MATCH", "source_effective_at": checked_at}).scalar_one()
        lien_ids.append((lien.instrument_number or "", lien_id))
    for parent_key, child_key, relation, confidence in relationships:
        parent = next((lid for key, lid in lien_ids if key == parent_key), None)
        child = next((lid for key, lid in lien_ids if key == child_key), None)
        if parent and child:
            connection.execute(text("""INSERT INTO lien_relationships(parent_lien_id, child_lien_id, relationship_type, confidence)
                VALUES(CAST(:parent AS UUID), CAST(:child AS UUID), :relationship, :confidence)
                ON CONFLICT DO NOTHING"""), {"parent": parent, "child": child, "relationship": relation, "confidence": confidence})
    connection.execute(text("""UPDATE lien_source_runs SET status='SUCCESS', records_found=:count, checked_at=:checked_at
        WHERE id=CAST(:run_id AS UUID)"""), {"run_id": run_id, "count": len(liens), "checked_at": checked_at})
    connection.execute(text("""
        INSERT INTO lien_category_coverage(
            property_id, category, source_name, status, record_count, source_url, message, checked_at, updated_at
        ) VALUES(CAST(:property_id AS UUID), 'COUNTY_LAND_RECORDS', 'Monmouth County OPRS',
            :status, :record_count, :source_url, :message, :checked_at, :checked_at)
        ON CONFLICT(property_id, category, source_name) DO UPDATE SET
            status=EXCLUDED.status, record_count=EXCLUDED.record_count,
            source_url=EXCLUDED.source_url, message=EXCLUDED.message,
            checked_at=EXCLUDED.checked_at, updated_at=EXCLUDED.updated_at
    """), {"property_id": sale["property_id"], "status": "RECORDS_FOUND" if liens else "CHECKED_NO_MATCH",
            "record_count": len(liens), "source_url": MONMOUTH_OPRS_URL,
            "message": ("Public index records were returned; matching and legal status remain preliminary."
                         if liens else "The public index returned no matching rows. This does not confirm clean title."),
            "checked_at": checked_at})
    coverage = SourceCoverage(source_name="Monmouth County OPRS", source_type="COUNTY_LAND_RECORDS",
                              status=SourceStatus.SUCCESS, checked_at=checked_at, source_url=MONMOUTH_OPRS_URL,
                              records_found=len(liens), message="Public index search completed; document images and legal conclusions are not included.")
    report = calculate_lien_risk(str(sale["property_id"]), liens, _coverage({"COUNTY_LAND_RECORDS": coverage}))
    connection.execute(text("""INSERT INTO lien_risk_reports(property_id,sheriff_sale_id,risk_score,risk_level,confidence_score,known_exposure,components,flags,source_coverage,calculation_version,calculated_at)
      VALUES(CAST(:property_id AS UUID),CAST(:sale_id AS UUID),:risk_score,:risk_level,:confidence_score,:known_exposure,CAST(:components AS JSONB),CAST(:flags AS JSONB),CAST(:coverage AS JSONB),:version,:calculated_at)"""),
      {"property_id": sale["property_id"], "sale_id": sale["sheriff_sale_id"], "risk_score": report.risk_score,
       "risk_level": report.risk_level, "confidence_score": report.confidence_score, "known_exposure": report.known_exposure,
       "components": json.dumps(report.components), "flags": json.dumps([item.model_dump(mode="json") for item in report.flags]),
       "coverage": json.dumps([item.model_dump(mode="json") for item in report.source_coverage]),
       "version": report.calculation_version, "calculated_at": report.calculated_at})
    return {"status": "COMPLETED", "source": SOURCE_NAME, "records_found": len(liens),
            "risk_score": report.risk_score, "risk_level": report.risk_level}


def _refresh_liens_sync(property_id: str):
    query = text("""
        SELECT p.id::text AS property_id, ss.id::text AS sheriff_sale_id,
               ss.plaintiff, ss.defendant, ss.court_case_number, ss.source_url, ss.description_text,
               p.normalized_address, p.city, p.county, p.block, p.lot, p.qualifier, p.pams_pin
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
        if (sale["county"] or "").strip().lower() == "monmouth":
            return _refresh_monmouth(connection, dict(sale))
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


def _run_lien_job(job_id: str, property_id: str) -> None:
    with engine.begin() as connection:
        connection.execute(text("UPDATE ingestion_jobs SET status='RUNNING', started_at=NOW() WHERE id=CAST(:job_id AS UUID)"), {"job_id": job_id})
    try:
        result = _refresh_liens_sync(property_id)
        with engine.begin() as connection:
            connection.execute(text("""UPDATE ingestion_jobs SET status='SUCCEEDED', records_found=:records_found, completed_at=NOW()
                WHERE id=CAST(:job_id AS UUID)"""), {"job_id": job_id, "records_found": result.get("records_found", 0)})
    except Exception as exc:
        with engine.begin() as connection:
            connection.execute(text("""UPDATE ingestion_jobs SET status='FAILED', error_message=:error_message, completed_at=NOW()
                WHERE id=CAST(:job_id AS UUID)"""), {"job_id": job_id, "error_message": str(exc)})


# Refreshing queries outside lien sources, so only developers can trigger it.
@router.post("/{property_id}/liens/refresh", dependencies=[Depends(require_developer)])
def refresh_liens(property_id: str, background_tasks: BackgroundTasks):
    """Queue a refresh; external source requests never block property rendering."""
    with engine.begin() as connection:
        sale = connection.execute(text("""
            SELECT p.county FROM properties p WHERE p.id=CAST(:property_id AS UUID)
        """), {"property_id": property_id}).mappings().first()
        if sale is None:
            raise HTTPException(status_code=404, detail="Property not found")
        job_id = connection.execute(text("""
            INSERT INTO ingestion_jobs(property_id, source, county, status)
            VALUES(CAST(:property_id AS UUID), 'LIEN_REFRESH', :county, 'QUEUED') RETURNING id::text
        """), {"property_id": property_id, "county": sale["county"]}).scalar_one()
    background_tasks.add_task(_run_lien_job, job_id, property_id)
    return {"job_id": job_id, "status": "QUEUED"}


@router.get("/{property_id}/liens")
def get_liens(property_id: str):
    with engine.connect() as connection:
        rows = connection.execute(text("""
            SELECT pl.id::text, pl.lien_type, pl.lien_subtype, pl.status, pl.creditor_name,
                   pl.debtor_name, pl.original_amount, pl.current_amount, pl.recording_date,
                   pl.effective_date, pl.instrument_number, pl.docket_number, pl.case_number,
                   pl.is_foreclosing_lien, pl.match_confidence, pl.match_reason,
                   pl.priority_classification, pl.priority_confidence,
                   pl.survival_classification, pl.survival_confidence,
                   pl.requires_manual_review, pl.source_name, pl.source_url, pl.source_effective_at,
                   pl.source_record_id, pl.county, pl.municipality, pl.block, pl.lot, pl.qualifier, pl.pams_pin,
                   pl.property_address, pl.matching_method, raw.retrieved_at AS retrieved_at,
                   raw.ingestion_status
            FROM property_liens pl
            LEFT JOIN raw_lien_records raw ON raw.id = pl.raw_record_id
            WHERE pl.property_id = CAST(:property_id AS UUID)
            ORDER BY pl.requires_manual_review DESC, pl.current_amount DESC NULLS LAST
        """), {"property_id": property_id}).mappings().all()
    return {"items": [dict(row) for row in rows]}


@jobs_router.get("/{job_id}")
def get_lien_job(job_id: str):
    with engine.connect() as connection:
        row = connection.execute(text("""
            SELECT id::text AS job_id, property_id::text, source, county, started_at,
                   completed_at, status, records_found, error_message, created_at
            FROM ingestion_jobs WHERE id=CAST(:job_id AS UUID)
        """), {"job_id": job_id}).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Lien job not found")
    return dict(row)


@router.get("/{property_id}/lien-enrichment")
def get_lien_enrichment(property_id: str):
    """Return the latest fail-soft public-record enrichment for the property."""
    with engine.connect() as connection:
        row = connection.execute(text("""
            SELECT property_id::text, status, primary_lender,
                   municipal_violations_count, estimated_municipal_debt_usd,
                   outstanding_taxes_usd, tax_delinquency_status,
                   source_statuses, source_urls, raw_data, error_message, retrieved_at, updated_at
            FROM public_record_enrichments
            WHERE property_id = CAST(:property_id AS UUID)
        """), {"property_id": property_id}).mappings().first()
    return {"item": dict(row) if row else None}


def _summary_coverage(connection, property_id: str, county: str | None = None, municipality: str | None = None) -> list[SourceCoverage]:
    rows = connection.execute(text("""
        SELECT source_name, source_type, status, source_url, records_found,
               error_message, checked_at, source_updated_at
        FROM lien_source_runs
        WHERE property_id = CAST(:property_id AS UUID)
        ORDER BY checked_at DESC
    """), {"property_id": property_id}).mappings().all()
    latest: dict[str, dict] = {}
    for row in rows:
        latest.setdefault(row["source_type"], dict(row))
    result: list[SourceCoverage] = []
    for row in latest.values():
        try:
            status = SourceStatus(str(row["status"]))
        except ValueError:
            status = SourceStatus.MANUAL_REVIEW_REQUIRED
        result.append(SourceCoverage(
            source_name=row["source_name"], source_type=row["source_type"], status=status,
            checked_at=row["checked_at"], source_url=row["source_url"],
            records_found=row["records_found"] or 0, message=row["error_message"],
        ))
    source_types = {item.source_type for item in result}
    if not result:
        result.extend(_coverage())
        source_types = {item.source_type for item in result}
    for capability in [*county_capabilities(county), *municipal_capabilities(municipality, county)]:
        if capability.source_type in source_types:
            continue
        result.append(SourceCoverage(
            source_name=capability.source_name,
            source_type=capability.source_type,
            status=SourceStatus.MANUAL_REVIEW_REQUIRED,
            source_url=capability.url or None,
            message=f"{capability.access_status}: {capability.automation_note}",
        ))
    return result


@router.get("/{property_id}/lien-summary")
def get_lien_summary(property_id: str):
    """Return a deterministic, evidence-linked bidder-facing summary."""
    with engine.connect() as connection:
        sale = connection.execute(text("""
            SELECT p.id::text AS property_id, p.normalized_address, p.city, p.county,
                   p.municipality, p.block, p.lot, p.qualifier, p.pams_pin,
                   ss.defendant, ss.plaintiff, ss.court_case_number, ss.source_url
            FROM properties p JOIN sheriff_sales ss ON ss.property_id=p.id
            WHERE p.id=CAST(:property_id AS UUID)
            ORDER BY ss.current_sale_date DESC NULLS LAST LIMIT 1
        """), {"property_id": property_id}).mappings().first()
        if sale is None:
            raise HTTPException(status_code=404, detail="Property not found")
        lien_rows = connection.execute(text("""
            SELECT pl.id::text, pl.lien_type, pl.lien_subtype, pl.status, pl.creditor_name,
                   pl.debtor_name, pl.original_amount, pl.current_amount, pl.recording_date,
                   pl.effective_date, pl.instrument_number, pl.docket_number, pl.case_number,
                   pl.is_foreclosing_lien, pl.match_confidence, pl.match_reason,
                   pl.priority_classification, pl.priority_confidence,
                   pl.survival_classification, pl.survival_confidence,
                   pl.requires_manual_review, pl.source_name, pl.source_url,
                   pl.source_effective_at
            FROM property_liens pl WHERE pl.property_id=CAST(:property_id AS UUID)
            ORDER BY pl.requires_manual_review DESC, pl.current_amount DESC NULLS LAST
        """), {"property_id": property_id}).mappings().all()
        enrichment = connection.execute(text("""
            SELECT status, primary_lender, municipal_violations_count,
                   estimated_municipal_debt_usd, outstanding_taxes_usd,
                   tax_delinquency_status, source_statuses, source_urls,
                   error_message, retrieved_at, data_freshness_status
            FROM public_record_enrichments WHERE property_id=CAST(:property_id AS UUID)
        """), {"property_id": property_id}).mappings().first()
        coverage = _summary_coverage(connection, property_id, sale["county"], sale["municipality"] or sale["city"])
    if enrichment:
        source_statuses = enrichment.get("source_statuses") or {}
        source_urls = enrichment.get("source_urls") or []
        for source_key, raw_status in source_statuses.items():
            normalized = str(raw_status)
            try:
                source_status = SourceStatus(normalized)
            except ValueError:
                source_status = SourceStatus.MANUAL_REVIEW_REQUIRED
            coverage.append(SourceCoverage(
                source_name=source_key.replace("_", " ").title(),
                source_type=source_key.upper(),
                status=source_status,
                checked_at=enrichment.get("retrieved_at"),
                source_url=source_urls[0] if source_urls else None,
                records_found=0,
                message="Source result is recorded in the public-record enrichment audit." if source_status in {SourceStatus.SUCCESS, SourceStatus.PARTIAL} else normalized.replace("_", " "),
            ))
    liens = [LienRecord.model_validate(dict(row)) for row in lien_rows]
    report = calculate_lien_risk(property_id, liens, coverage)
    owners = tuple(value.strip() for value in (sale["defendant"] or "").replace(";", ",").split(",") if value.strip())
    identity = {
        "property_address": sale["normalized_address"], "county": sale["county"],
        "municipality": sale["municipality"] or sale["city"], "block": sale["block"],
        "lot": sale["lot"], "qualifier": sale["qualifier"], "pams_pin": sale["pams_pin"],
        "owner": owners[0] if owners else None, "case_number": sale["court_case_number"],
    }
    summary = build_preliminary_summary(report, coverage, liens, county=sale["county"], municipality=sale["municipality"], identity=identity, enrichment=dict(enrichment) if enrichment else None)
    return {
        "property_id": property_id,
        "summary": summary,
        "risk": report.model_dump(mode="json"),
        "liens": [item.model_dump(mode="json") for item in liens],
        "enrichment": dict(enrichment) if enrichment else None,
        "professional_title_search": get_professional_title_search().model_dump(),
    }


@router.get("/{property_id}/complaints")
def get_public_complaints(property_id: str):
    """Return publicly retrieved complaint records for the property."""
    with engine.connect() as connection:
        row = connection.execute(text("""
            SELECT raw_data->'socrata' AS complaints
            FROM public_record_enrichments
            WHERE property_id = CAST(:property_id AS UUID)
        """), {"property_id": property_id}).mappings().first()
    complaints = (row or {}).get("complaints") or []
    return {"items": complaints if isinstance(complaints, list) else []}


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
        coverage = _summary_coverage(connection, property_id)
    report = calculate_lien_risk(
        property_id,
        [LienRecord.model_validate(dict(row)) for row in rows],
        coverage,
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


@router.get("/{property_id}/lien-sources")
def get_lien_sources(property_id: str):
    with engine.connect() as connection:
        sale = connection.execute(text("SELECT county, municipality, city FROM properties WHERE id=CAST(:property_id AS UUID)"), {"property_id": property_id}).mappings().first()
        if sale is None:
            raise HTTPException(status_code=404, detail="Property not found")
        items = _summary_coverage(connection, property_id, sale["county"], sale["municipality"] or sale["city"])
    return {"items": [{
        "source_name": item.source_name, "source_type": item.source_type,
        "status": item.status.value, "checked_at": item.checked_at,
        "source_url": item.source_url, "records_found": item.records_found,
        "message": item.message,
    } for item in items]}


@router.get("/{property_id}/professional-title-search")
def get_professional_title_search_link(property_id: str):
    """Return the configured outbound professional-search link.

    The property id is validated so the CTA remains part of a real property
    detail experience. No property data is sent to the provider.
    """
    with engine.connect() as connection:
        exists = connection.execute(
            text("SELECT 1 FROM properties WHERE id = CAST(:property_id AS UUID)"),
            {"property_id": property_id},
        ).first()
    if exists is None:
        raise HTTPException(status_code=404, detail="Property not found")
    return {"property_id": property_id, "professional_title_search": get_professional_title_search().model_dump()}
