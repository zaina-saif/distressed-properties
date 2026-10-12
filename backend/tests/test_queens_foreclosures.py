from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock
import json
import pytest
from pipeline.queens.browser import AccessChallenge, CourtBrowser, challenged, court_url
from pipeline.queens.parsing import calendar_cases, parse_notice, pdf_text
from pipeline.queens_foreclosure_refresh import run

NOTICE = '''SUPREME COURT COUNTY OF QUEENS NOTICE OF SALE
Index No. 712345/2024. Pursuant to a Judgment dated January 2, 2026,
I will sell at public auction at Queens Supreme Court, 88-11 Sutphin Blvd,
Jamaica, NY on November 12, 2026 at 10:00 AM. Premises known as
123-45 Main Street, Flushing, NY 11354. Approximate amount of judgment
$456,789.12 plus interest and costs. Opening bid $10,000.00.'''
URL = 'https://iapps.courts.state.ny.us/nyscef/ViewDocument?docIndex=abc'


def parsed(text=NOTICE):
    return parse_notice(text, '712345/2024', URL, 'abc')


def test_notice_fields_and_money_semantics():
    r = parsed()
    assert r['review_reasons'] == []
    assert (r['street'], r['city'], r['zip_code']) == ('123-45 Main Street', 'Flushing', '11354')
    assert r['sale_date'] == '2026-11-12'
    assert r['judgment_amount'] == '456789.12'


def test_missing_judgment_is_not_opening_bid():
    assert parsed(NOTICE.replace('Approximate amount of judgment\n$456,789.12', 'Debt $456,789.12'))['judgment_amount'] is None


@pytest.mark.parametrize('before,after,reason', [
    ('712345/2024', '712346/2024', 'case_index_missing_or_ambiguous'),
    ('Premises known as', 'Auction venue', 'property_address_missing_or_ambiguous'),
    ('November 12, 2026', 'a date to be announced', 'auction_date_missing_or_ambiguous'),
    ('NOTICE OF SALE', 'NOTICE OF APPEARANCE', 'not_notice_of_sale'),
])
def test_unsupported_notices_require_review(before, after, reason):
    assert reason in parsed(NOTICE.replace(before, after))['review_reasons']


def test_conflicting_amounts_and_addresses_are_not_guessed():
    r = parsed(NOTICE + ' Judgment amount $900,000.00. Premises known as 555 Other Street, Jamaica, NY 11432.')
    assert 'conflicting_judgment_amounts' in r['review_reasons']
    assert 'property_address_missing_or_ambiguous' in r['review_reasons']
    assert r['judgment_amount'] is None


def test_calendar_indices_deduplication_and_county():
    assert calendar_cases('Queens 712345/2024 712345 / 2024 098765-2020') == ['098765/2020', '712345/2024']
    for value in ['Kings 712345/2024', 'Queens unreadable']:
        with pytest.raises(ValueError):
            calendar_cases(value)
    assert calendar_cases('Queens no cases') == []
    with pytest.raises(ValueError, match='not a PDF'):
        pdf_text(b'<html>captcha</html>')


@pytest.mark.parametrize('html', ['Just a moment', '<div class="h-captcha">', 'g-recaptcha', 'Access Denied'])
def test_challenges(html):
    assert challenged(html)


@pytest.mark.parametrize('url', ['https://evil.test/file.pdf', 'http://iapps.courts.state.ny.us/x', 'https://iapps.courts.state.ny.us.evil.test/x'])
def test_untrusted_urls(url):
    with pytest.raises(ValueError):
        court_url(url)


def options(tmp_path, dry=False):
    return SimpleNamespace(run_dir=tmp_path, start=date(2026, 10, 1), end=date(2026, 11, 1), dry_run=dry)


def browser():
    b = Mock()
    b.calendars.return_value = (['712345/2024'], ['https://iapps.courts.state.ny.us/webcivil/calendar.pdf'])
    b.notices.return_value = [URL, URL]
    b.pdf.return_value = (b'fake-test-fixture', NOTICE)
    return b


def test_end_to_end_orchestration_deduplicates_notices(tmp_path, monkeypatch):
    monkeypatch.setattr('pipeline.queens_foreclosure_refresh.time.sleep', lambda _: None)
    loader = Mock(return_value={'created': 1})
    assert run(options(tmp_path), lambda _: browser(), loader) == 0
    assert len(loader.call_args.args[0]) == 1
    assert json.loads((tmp_path / 'report.json').read_text())['created'] == 1


def test_late_challenge_never_imports_partial_or_stale_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr('pipeline.queens_foreclosure_refresh.time.sleep', lambda _: None)
    (tmp_path / 'snapshot.json').write_text('[{"old":true}]')
    b = browser()
    b.calendars.return_value = (['712345/2024', '799999/2024'], [])
    b.notices.side_effect = [[URL], AccessChallenge('captcha')]
    loader = Mock()
    assert run(options(tmp_path), lambda _: b, loader) == 2
    loader.assert_not_called()
    assert json.loads((tmp_path / 'report.json').read_text())['status'] == 'access_challenge'


def test_dry_run_and_conflicting_notices(tmp_path, monkeypatch):
    monkeypatch.setattr('pipeline.queens_foreclosure_refresh.time.sleep', lambda _: None)
    b = browser()
    b.pdf.side_effect = [(b'a', NOTICE), (b'b', NOTICE.replace('November 12', 'November 19'))]
    loader = Mock()
    assert run(options(tmp_path, dry=True), lambda _: b, loader) == 3
    loader.assert_not_called()
    assert json.loads((tmp_path / 'report.json').read_text())['accepted'] == 0


def test_pdf_challenge_is_not_retried(tmp_path):
    context = Mock()
    response = context.request.get.return_value
    response.status = 403
    response.headers = {'content-type': 'text/html'}
    response.text.return_value = 'captcha'
    b = CourtBrowser(context, tmp_path)
    with pytest.raises(AccessChallenge):
        b.pdf(URL)
    assert context.request.get.call_count == 1


def test_transient_pdf_errors_retry_but_exhaustion_fails(tmp_path, monkeypatch):
    monkeypatch.setattr('pipeline.queens.browser.time.sleep', lambda _: None)
    context = Mock()
    response = context.request.get.return_value
    response.status = 503
    response.headers = {'content-type': 'text/html'}
    response.text.return_value = 'Service unavailable'
    response.ok = False
    with pytest.raises(RuntimeError):
        CourtBrowser(context, tmp_path).pdf(URL)
    assert context.request.get.call_count == 3


def test_pdf_content_type_does_not_hide_denied_status(tmp_path):
    context = Mock()
    response = context.request.get.return_value
    response.status = 403
    response.headers = {'content-type': 'application/pdf'}
    with pytest.raises(AccessChallenge):
        CourtBrowser(context, tmp_path).pdf(URL)


def test_auction_details():
    r = parsed()
    assert r['auction_time'] == '10:00 AM'
    assert r['auction_location'] == 'Queens Supreme Court, 88-11 Sutphin Blvd, Jamaica, NY'


def test_real_pdf_text_extraction():
    # Synthetic PDF fixture (not a real court record), including a valid xref.
    stream = b'BT /F1 12 Tf 40 700 Td (Queens Calendar Index 712345/2024) Tj ET'
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
               b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream']
    body = b'%PDF-1.4\n'
    offsets = []
    for number, obj in enumerate(objects, 1):
        offsets.append(len(body))
        body += str(number).encode() + b' 0 obj\n' + obj + b'\nendobj\n'
    xref = len(body)
    body += b'xref\n0 6\n0000000000 65535 f \n'
    body += b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets)
    body += b'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n' + str(xref).encode() + b'\n%%EOF'
    assert calendar_cases(pdf_text(body)) == ['712345/2024']


def test_hidden_court_captcha_widget_is_not_an_active_challenge():
    from pipeline.queens.browser import challenged
    assert not challenged('''<html><body><form><div class="h-captcha" style="display: none"><iframe title="captcha" style="display: none"></iframe></div><input type="submit" value="Find Calendar"></form></body></html>''')
    assert challenged('<html><body><iframe title="hCaptcha security challenge" src="https://captcha.test"></iframe></body></html>')


def test_invisible_hcaptcha_on_a_results_page_is_not_a_challenge():
    from pipeline.queens.browser import challenged
    page = '''<html><body><table><tr><td>Calendar for Queens</td></tr></table>
    <div class="h-captcha" data-sitekey="x" data-size="invisible"></div>
    <a href="/webcivil/calendar.pdf">Calendar PDF</a></body></html>'''
    assert not challenged(page)
