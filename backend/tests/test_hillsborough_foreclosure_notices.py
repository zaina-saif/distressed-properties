from datetime import date
import pytest

from pipeline.load_hillsborough_foreclosure_notices import validate
from pipeline.scrape_hillsborough_foreclosure_notices import discover, parse_notice


def test_parse_published_foreclosure_notice() -> None:
    html = '''<html><head><meta property="article:published_time"
      content="2026-09-04T00:00:00-04:00"></head><body><h1>26-03213H</h1>
      <div class="story_body">NOTICE OF FORECLOSURE SALE<br>CASE NO.: 2025-CA-009939<br>
      Final judgment entered on August 20, 2026.<br>
      Clerk will sell on October 7, 2026 at www.hillsborough.realforeclose.com.<br>
      Property Address: 6343 Osprey Lake Circle, Riverview, FL 33578</div></body></html>'''
    record = parse_notice(html,
                          'https://legals.businessobserverfl.com/news/2026/sep/04/26-03213h/',
                          date(2026, 9, 17))
    assert record is not None
    assert record['court_case_number'] == '2025-CA-009939'
    assert record['sale_date'] == '2026-10-07'
    assert record['street_address'] == '6343 Osprey Lake Circle'
    assert record['status'] == 'scheduled_unverified'
    assert parse_notice(html, record['source_url'], date(2026, 11, 1)) is None


def test_discover_only_foreclosure_cards() -> None:
    html = '''<div class="wrap__masonary-card"><h4 class="card-title"><a href="/one/">1</a></h4>
      <p>NOTICE OF FORECLOSURE SALE</p></div>
      <div class="wrap__masonary-card"><h4 class="card-title"><a href="/two/">2</a></h4>
      <p>Vehicle public sale</p></div>'''
    assert discover(html) == ['https://legals.businessobserverfl.com/one/']


def test_validate_rejects_wrong_jurisdiction() -> None:
    record = {'state': 'NY', 'county': 'Hillsborough', 'source_system':
              'fl_hillsborough_published_foreclosure_notice', 'source_url':
              'https://legals.businessobserverfl.com/news/x', 'street_address': '123 Main St',
              'court_case_number': 'x', 'sale_date': '2026-10-07'}
    with pytest.raises(ValueError, match='jurisdiction'):
        validate({'source_index_url': 'https://legals.businessobserverfl.com/news/hillsborough/',
                  'source_checked_date': '2026-09-17', 'records': [record]}, date(2026, 9, 17))
