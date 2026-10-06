"""Shared loader for sale listings that arrive as complete snapshots of a county's
upcoming sales (RealAuction, South Carolina Master-in-Equity lists, ...).

Callers turn their source's rows into Sale records; this module writes the
property, the sale, its raw payload and status history, and retires open sales
that are missing from the snapshot."""
import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from sqlalchemy import text

from app.database.session import engine

BATCH = 100
MONEY = re.compile(r"\$?\s*([\d,]+(?:\.\d+)?)")


@dataclass
class Sale:
    case: str  # unique per county and source; stored as sheriff_number
    street: str
    city: str | None
    zip_code: str | None
    sale_date: date | None
    status: str
    raw: dict
    raw_status: str | None = None
    parcel: str | None = None
    upset: float | None = None
    judgment: float | None = None
    plaintiff: str | None = None
    defendant: str | None = None
    attorney: str | None = None
    result: str | None = None
    property_number: str | None = None
    extra: dict = field(default_factory=dict)


def money(value):
    """First dollar amount in a string ("$81,305.28" -> 81305.28), else None."""
    match = MONEY.search(value or "")
    return float(match.group(1).replace(",", "")) if match else None


def usable_address(sale):
    """A city and a street that starts with a house number; not "UNKNOWN", a lot
    description, or a city/ZIP line misplaced in the street field."""
    return bool(sale.city and re.match(r"\d", sale.street or "") and not re.search(r",\s*\d{5}", sale.street))


def load_sales(state, county, source, source_url, sales, job):
    """Upsert one county's complete snapshot of sales from `source`."""
    now = datetime.now(timezone.utc)
    run = str(uuid.uuid4())
    created = updated = skipped = 0
    with engine.begin() as connection:
        connection.execute(text("""INSERT INTO scrape_runs(id,job_name,county,source_system,started_at,status,records_found)
            VALUES(:id,:job,:county,:source,:now,'running',:count)"""),
            {"id": run, "job": job, "county": county, "source": source, "now": now, "count": len(sales)})
    # Short transactions: one long one can outlive the Supabase pooler connection.
    for start in range(0, len(sales), BATCH):
        with engine.begin() as connection:
            for sale in sales[start:start + BATCH]:
                if not usable_address(sale):
                    skipped += 1
                    continue
                created_one = _upsert(connection, state, county, source, source_url, sale, run, now)
                created += created_one
                updated += not created_one
    with engine.begin() as connection:
        # The snapshot lists every upcoming sale, so an open sale that is missing
        # has been sold, cancelled or pulled; the source does not say which.
        dropped = connection.execute(text("""UPDATE sheriff_sales SET current_status='sold_or_cancelled_unverified',
            updated_at=NOW() WHERE state=:state AND county=:county AND source_system=:source
            AND current_status IN ('scheduled','adjourned') AND sheriff_number <> ALL(:numbers) RETURNING id"""),
            {"state": state, "county": county, "source": source, "numbers": [sale.case for sale in sales]}).scalars().all()
        for sale_id in dropped:
            connection.execute(text("""INSERT INTO sheriff_sale_status_history(id,sheriff_sale_id,status,observed_at,
                source_url,raw_status) VALUES(:id,:sale_id,'sold_or_cancelled_unverified',:now,:url,
                'no longer on the sale listing')"""),
                {"id": str(uuid.uuid4()), "sale_id": sale_id, "now": now, "url": source_url})
        connection.execute(text("""UPDATE scrape_runs SET completed_at=NOW(),status='completed',records_created=:created,
            records_updated=:updated WHERE id=:id"""), {"created": created, "updated": updated, "id": run})
    return {"created": created, "updated": updated, "skipped": skipped, "no_longer_listed": len(dropped)}


def _upsert(connection, state, county, source, source_url, sale, run, now):
    normalized = (f"{sale.street}, {sale.city}, {state} {sale.zip_code}" if sale.zip_code
                  else f"{sale.street}, {sale.city}, {state}")
    address_hash = hashlib.sha256(f"{state}|{county}|{normalized.upper()}".encode()).hexdigest()
    property_id = connection.execute(text("""INSERT INTO properties(id,normalized_address,street_address,
        city,municipality,county,state,zip_code,parcel_number,address_hash,data_quality_score)
        VALUES(:id,:normalized,:street,:city,:city,:county,:state,:zip,:parcel,:hash,70)
        ON CONFLICT(address_hash) DO UPDATE SET parcel_number=COALESCE(properties.parcel_number,
        EXCLUDED.parcel_number),updated_at=NOW() RETURNING id"""),
        {"id": str(uuid.uuid4()), "normalized": normalized, "street": sale.street, "city": sale.city,
         "county": county, "state": state, "zip": sale.zip_code, "parcel": sale.parcel,
         "hash": address_hash}).scalar_one()
    content_hash = hashlib.sha256(json.dumps(sale.raw, sort_keys=True, default=str).encode()).hexdigest()
    connection.execute(text("""INSERT INTO raw_scrape_records(id,scrape_run_id,state,county,source_record_id,
        source_url,raw_payload,content_hash,parsing_status,scraped_at) VALUES(:id,:run,:state,:county,:case,
        :url,CAST(:payload AS JSONB),:hash,'parsed',:now) ON CONFLICT DO NOTHING"""),
        {"id": str(uuid.uuid4()), "run": run, "state": state, "county": county, "case": sale.case,
         "url": source_url, "payload": json.dumps(sale.raw, default=str), "hash": content_hash, "now": now})
    params = {
        "property_id": property_id, "state": state, "county": county, "number": sale.case, "case": sale.case,
        "sale_date": sale.sale_date, "status": sale.status, "url": source_url, "now": now, "hash": content_hash,
        "source": source, "property_number": sale.property_number, "map_number": sale.parcel,
        "upset": sale.upset, "judgment": sale.judgment, "plaintiff": sale.plaintiff, "defendant": sale.defendant,
        "attorney": sale.attorney, "result": sale.result,
    }
    existing = connection.execute(text("""SELECT id FROM sheriff_sales WHERE state=:state AND county=:county
        AND source_system=:source AND sheriff_number=:number"""), params).scalar()
    params["id"] = existing or str(uuid.uuid4())
    if existing:
        connection.execute(text("""UPDATE sheriff_sales SET property_id=:property_id,court_case_number=:case,
            current_sale_date=:sale_date,current_status=:status,upset_price=COALESCE(:upset,upset_price),
            judgment_amount=COALESCE(:judgment,judgment_amount),plaintiff=COALESCE(:plaintiff,plaintiff),
            defendant=COALESCE(:defendant,defendant),sale_attorney=COALESCE(:attorney,sale_attorney),
            source_url=:url,last_seen_at=:now,last_scraped_at=:now,raw_source_hash=:hash,
            property_number=COALESCE(:property_number,property_number),map_number=COALESCE(:map_number,map_number),
            sale_result=:result,updated_at=NOW() WHERE id=:id"""), params)
    else:
        connection.execute(text("""INSERT INTO sheriff_sales(id,property_id,state,county,sheriff_number,
            court_case_number,plaintiff,defendant,original_sale_date,current_sale_date,current_status,upset_price,
            judgment_amount,source_url,source_system,first_seen_at,last_seen_at,last_scraped_at,raw_source_hash,
            is_active,property_number,map_number,sale_attorney,sale_result) VALUES(:id,:property_id,:state,:county,
            :number,:case,:plaintiff,:defendant,:sale_date,:sale_date,:status,:upset,:judgment,:url,:source,:now,
            :now,:now,:hash,TRUE,:property_number,:map_number,:attorney,:result)"""), params)
    connection.execute(text("""INSERT INTO sheriff_sale_status_history(id,sheriff_sale_id,status,sale_date,
        upset_price,observed_at,source_url,raw_status)
        SELECT :history_id,:id,:status,:sale_date,:upset,:now,:url,:raw_status
        WHERE NOT EXISTS(SELECT 1 FROM sheriff_sale_status_history WHERE sheriff_sale_id=:id
          AND status=:status AND sale_date IS NOT DISTINCT FROM :sale_date)"""),
        {**params, "history_id": str(uuid.uuid4()), "raw_status": sale.raw_status})
    return not existing
