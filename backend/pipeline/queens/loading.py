"""Atomic partial-snapshot import into the existing operational PostgreSQL schema."""
from datetime import date, datetime, timezone
from decimal import Decimal
import uuid

from sqlalchemy import bindparam, text

from .counties import COUNTIES

SOURCE = COUNTIES['queens'].source
# Court sources that already list a county's auctions by index number (Kings and Bronx
# Notice of Sale PDFs); a case they hold is not loaded a second time from NYSCEF.
OTHER_COURT_SOURCES = ('ny_court_foreclosure_auction', 'nyc_kings_court_foreclosure_index')


def load_records(records, engine=None, county='Queens'):
    # Lazy imports keep parsing and collection usable without database credentials.
    from pipeline.sale_listing_loader import Sale, _upsert
    if engine is None:
        from app.database.session import engine
    county = COUNTIES[county.lower()]
    source, name = county.source, county.name
    identities = [r['case'] for r in records]
    if len(set(identities)) != len(identities):
        raise ValueError('Duplicate case identities in snapshot')
    now = datetime.now(timezone.utc)
    run = str(uuid.uuid4())
    created = updated = skipped = other_source = 0
    with engine.begin() as connection:
        # Serialize this source across local runs and scheduled runs.
        connection.execute(text("SELECT pg_advisory_xact_lock(hashtext(:source))"), {'source': source + name})
        connection.execute(text("""INSERT INTO scrape_runs
            (id,job_name,county,source_system,started_at,status,records_found)
            VALUES(:id,:source,:county,:source,:now,'running',:count)"""),
            {'id': run, 'source': source, 'county': name, 'now': now, 'count': len(records)})
        for record in records:
            if record['review_reasons']:
                raise ValueError('Review records cannot be loaded')
            sale_date = date.fromisoformat(record['sale_date'])
            if connection.execute(text("""SELECT 1 FROM sheriff_sales WHERE state='NY' AND county=:county
                AND source_system IN :others AND court_case_number=:case LIMIT 1""").bindparams(
                    bindparam('others', expanding=True)),
                    {'county': name, 'others': list(OTHER_COURT_SOURCES), 'case': record['case']}).first():
                other_source += 1
                continue
            number = county.number_prefix + record['case']
            existing = connection.execute(text("""SELECT current_status, current_sale_date,
                judgment_amount, raw_source_hash FROM sheriff_sales
                WHERE state='NY' AND county=:county AND source_system=:source
                AND sheriff_number=:number FOR UPDATE"""), {'county': name, 'source': source, 'number': number}).first()
            # Do not reopen resolved sales or replace an existing date with an older notice.
            if existing and (existing[0] not in ('scheduled_unverified', 'date_passed_unverified')
                             or (existing[1] and existing[1].date() > sale_date)):
                skipped += 1
                continue
            sale = Sale(case=number, street=record['street'], city=record['city'],
                        zip_code=record['zip_code'], sale_date=sale_date,
                        status='scheduled_unverified' if sale_date >= date.today() else 'date_passed_unverified',
                        raw=record, raw_status='Advertised in NYSCEF Notice of Sale; outcome unverified',
                        # Existing financial figures may have been manually corrected.
                        judgment=(existing[2] if existing and existing[2] is not None else
                                  Decimal(record['judgment_amount']) if record['judgment_amount'] else None))
            new = _upsert(connection, 'NY', name, source, record['source_url'], sale, run, now)
            connection.execute(text("""UPDATE sheriff_sales SET court_case_number=:case,
                description_text=:details,is_active=:active,
                judgment_source_url=CASE WHEN :new_judgment THEN :url ELSE judgment_source_url END
                WHERE state='NY' AND county=:county AND source_system=:source AND sheriff_number=:number"""),
                {'case': record['case'], 'details': record['raw_text'], 'active': sale_date >= date.today(),
                 'county': name, 'source': source, 'number': number, 'url': record['source_url'],
                 'new_judgment': bool(record['judgment_amount'] and (not existing or existing[2] is None))})
            created += bool(new)
            updated += not new
        connection.execute(text("""UPDATE scrape_runs SET status='completed',completed_at=NOW(),
            records_created=:created,records_updated=:updated WHERE id=:id"""),
            {'id': run, 'created': created, 'updated': updated})
    # This is a discovery window, never a full county snapshot. No retirement pass.
    return {'created': created, 'updated': updated, 'skipped': skipped, 'already_listed': other_source}
