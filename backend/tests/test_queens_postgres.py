"""Optional real PostgreSQL integration test in a disposable schema.

QUEENS_TEST_DATABASE_URL must point to a local test server, never production.
"""
import os
from pathlib import Path
import uuid
from decimal import Decimal
from urllib.parse import urlparse

import pytest
from sqlalchemy import create_engine, text

from test_queens_foreclosures import parsed


@pytest.fixture
def db():
    url = os.getenv('QUEENS_TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set QUEENS_TEST_DATABASE_URL for PostgreSQL integration')
    if urlparse(url).hostname not in ('127.0.0.1', 'localhost'):
        pytest.fail('Integration test requires a local disposable PostgreSQL server')
    schema = 'queens_test_' + uuid.uuid4().hex
    base = create_engine(url)
    with base.begin() as c:
        c.execute(text(f'CREATE SCHEMA {schema}'))
    engine = create_engine(url, connect_args={'options': f'-csearch_path={schema},public'})
    try:
        migrations = Path(__file__).resolve().parents[1] / 'migrations'
        with engine.connect() as c:
            for name in ['001_initial_schema.sql', '011_multistate_sales.sql', '015_pa_sheriff_sale_parcel_fields.sql', '026_judgment_provenance.sql']:
                c.exec_driver_sql((migrations / name).read_text())
            # The production schema has these legacy columns, added before the
            # numbered migrations began covering all property/listing fields.
            c.exec_driver_sql('''ALTER TABLE properties ADD COLUMN parcel_number TEXT,
                ADD COLUMN latitude DOUBLE PRECISION, ADD COLUMN longitude DOUBLE PRECISION;
                ALTER TABLE sheriff_sales ADD COLUMN original_sale_date TIMESTAMPTZ,
                ADD COLUMN description_text TEXT;''')
            c.commit()
        yield engine
    finally:
        engine.dispose()
        with base.begin() as c:
            c.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        base.dispose()


def count(db, table):
    with db.connect() as c:
        return c.execute(text(f'SELECT count(*) FROM {table}')).scalar_one()


def test_idempotence_preservation_and_atomicity(db):
    from pipeline.queens.loading import load_records
    row = parsed()
    assert load_records([row], db)['created'] == 1
    assert load_records([row], db)['updated'] == 1
    for table in ['properties', 'sheriff_sales', 'raw_scrape_records', 'sheriff_sale_status_history']:
        assert count(db, table) == 1
    with db.begin() as c:
        c.execute(text('UPDATE sheriff_sales SET judgment_amount=123456.78'))
    load_records([{**row, 'judgment_amount': None}], db)
    with db.connect() as c:
        assert c.execute(text('SELECT judgment_amount FROM sheriff_sales')).scalar_one() == Decimal('123456.78')
    runs = count(db, 'scrape_runs')
    with pytest.raises(ValueError):
        load_records([{**row, 'case': '799999/2024'}, {**row, 'review_reasons': ['bad']}], db)
    assert count(db, 'sheriff_sales') == 1
    assert count(db, 'scrape_runs') == runs
    with db.begin() as c:
        c.execute(text("UPDATE sheriff_sales SET current_status='sold'"))
    assert load_records([row], db)['skipped'] == 1
    load_records([], db)
    with db.connect() as c:
        assert c.execute(text('SELECT current_status FROM sheriff_sales')).scalar_one() == 'sold'


def test_other_counties_load_under_their_own_source_and_skip_cases_already_listed(db):
    from pipeline.queens.loading import load_records
    from test_queens_foreclosures import NASSAU, URL
    from pipeline.queens.counties import county
    from pipeline.queens.parsing import parse_notice
    row = parse_notice(NASSAU, '712345/2024', URL, 'abc', county('Nassau'))
    assert load_records([row], db, county='Nassau')['created'] == 1
    with db.connect() as c:
        assert c.execute(text("SELECT county, source_system, sheriff_number FROM sheriff_sales")).one() == (
            'Nassau', 'ny_nyscef_foreclosure', 'NASSAU-NYSCEF-712345/2024')
    with db.begin() as c:
        c.execute(text("""UPDATE sheriff_sales SET county='Kings', source_system='ny_court_foreclosure_auction',
            court_case_number='712345/2024'"""))
    assert load_records([{**row, 'county': 'Kings'}], db, county='Kings')['already_listed'] == 1
    assert count(db, 'sheriff_sales') == 1
