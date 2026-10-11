"""Playwright adaptation of nyscef_scraper's guest/case/document workflow.

Foundation: https://github.com/AtheequeFurkhan/nyscef_scraper (scraper.py v18).
Reimplemented for the existing Playwright dependency; no upstream code vendored.
Court selection, document rows and pagination follow the upstream workflow.
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import Error as PlaywrightError, TimeoutError as BrowserTimeout

from .parsing import digest, indices, pdf_text, calendar_cases

CALENDAR = "https://iapps.courts.state.ny.us/webcivil/FCASCalendarSearch"
NYSCEF = "https://iapps.courts.state.ny.us/nyscef/CaseSearch"
LOG = logging.getLogger(__name__)


class AccessChallenge(RuntimeError):
    pass


class LayoutChanged(RuntimeError):
    pass


def court_url(url: str) -> str:
    p = urlparse(url)
    if p.scheme != "https" or p.hostname != "iapps.courts.state.ny.us" or p.port not in (None, 443) or p.username or p.password:
        raise ValueError("Expected an HTTPS court URL")
    return url


def challenged(html: str) -> bool:
    """Detect an active block, not the courts' permanently hidden captcha widget."""
    if re.search(r"just a moment|challenges\.cloudflare\.com|cf-chl-|access denied", html, re.I):
        return True
    soup = BeautifulSoup(html, 'html.parser')
    for node in soup.select('script,style,noscript'):
        node.decompose()
    for node in list(soup.find_all(True)):
        if node.attrs is None:
            continue
        style = (node.get('style') or '').replace(' ', '').lower()
        classes = node.get('class') or []
        if ('display:none' in style or 'visibility:hidden' in style
                or node.get('aria-hidden') == 'true' or 'hidden' in classes):
            node.decompose()
    visible_text = soup.get_text(' ', strip=True)
    visible_markup = ' '.join(' '.join(node.get('class') or []) for node in soup.find_all(True) if node.attrs)
    visible_captcha = bool(re.search(r"h-captcha|g-recaptcha|captcha|challenge", visible_markup, re.I)) or any(re.search(r"captcha|challenge|verify|robot", ' '.join(
        [node.get('src', ''), node.get('title', ''), node.get('aria-label', '')]), re.I)
        for node in soup.select('iframe'))
    return visible_captcha or bool(re.search(
        r"captcha|verify you are human|complete the security check|unusual traffic|access denied|robot check",
        visible_text, re.I))


class CourtBrowser:
    def __init__(self, context, folder: Path, assisted=False, operator_timeout=600):
        self.context, self.folder = context, folder
        self.assisted, self.operator_timeout = assisted, operator_timeout
        self.page = context.new_page()
        self.page.set_default_timeout(15000)
        folder.mkdir(parents=True, exist_ok=True)

    def guard(self):
        try:
            active = challenged(self.page.content())
        except PlaywrightError:
            active = True
        if not active:
            return
        if not self.assisted:
            raise AccessChallenge("Court access challenge: rerun with --assisted on the operator machine")
        LOG.warning("Complete the court challenge and submit the search in the visible browser; waiting up to %s seconds", self.operator_timeout)
        end = time.monotonic() + self.operator_timeout
        while time.monotonic() < end:
            self.page.wait_for_timeout(1000)
            try:
                if not challenged(self.page.content()):
                    return
            except PlaywrightError:
                continue
        raise AccessChallenge("Operator challenge timeout")

    def goto(self, url, check_access=True):
        for attempt in range(3):
            try:
                response = self.page.goto(court_url(url), wait_until="domcontentloaded")
                if response and response.status in (401, 403):
                    self.guard()
                    if not self.assisted:
                        raise AccessChallenge("Court denied access")
                    # The operator may have navigated to the permitted result.
                    return
                if response and (response.status == 429 or response.status >= 500):
                    if attempt == 2:
                        raise RuntimeError("Court unavailable after retries")
                    time.sleep(2 ** attempt)
                    continue
                if response and response.status >= 400:
                    raise RuntimeError("Court returned an HTTP error")
                if check_access:
                    self.guard()
                return
            except BrowserTimeout:
                self.guard()
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)

    def pdf(self, url):
        url = court_url(url)
        for attempt in range(3):
            try:
                response = self.context.request.get(url, timeout=45000, max_redirects=0)
            except BrowserTimeout:
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)
                continue
            is_html = 'pdf' not in response.headers.get('content-type', '')
            if response.status in (401, 403) or (is_html and challenged(response.text())):
                raise AccessChallenge("PDF download encountered an access challenge")
            if response.status == 429 or response.status >= 500:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
            if not response.ok:
                raise RuntimeError("PDF download failed (redirects require visible navigation)")
            body = response.body()
            if not body.startswith(b"%PDF-"):
                raise ValueError("Response is not a PDF")
            path = self.folder / f"{digest(body)}.pdf"
            path.write_bytes(body)  # Keep image-only PDFs for operator OCR/review.
            return body, pdf_text(body)
        raise RuntimeError("PDF retries exhausted")

    def links(self, pattern):
        return [urljoin(self.page.url, a.get_attribute('href'))
                for a in self.page.locator('a[href]').all()
                if re.search(pattern, (a.inner_text() + ' ' + (a.get_attribute('href') or '')), re.I)]

    def calendars(self, start, end):
        # Fill before guard: invisible hCaptcha is attached to Find Calendar.
        self.goto(CALENDAR, check_access=False)
        if self.page.locator('#cboCourt').count():
            self.page.locator('#cboCourt').select_option('80')
            for suffix, day in [('calFromDate', start), ('calToDate', end)]:
                for prefix, value in [('month', day.month), ('date', day.day), ('year', day.year)]:
                    self.page.locator(f'#f_{prefix}{suffix}').fill(str(value))
                    self.page.locator(f'#f_{prefix}{suffix}').blur()
            parts = self.page.locator('#cboCourtPart option').all()
            matches = [p.get_attribute('value') for p in parts if re.search('foreclosure', p.inner_text(), re.I)]
            if len(matches) == 1:
                self.page.locator('#cboCourtPart').select_option(matches[0])
            # A part is optional in the WebCivil form. Searching all Queens
            # appearances avoids silently omitting foreclosure sessions whose
            # part labels differ; NYSCEF verifies each case type afterward.
            self.page.locator('#btnFindCalendar').click()
            self.guard()
        else:
            self.guard()
        urls = self.links(r'\.pdf\b|calendar.*pdf|pdf.*calendar')
        if not urls:
            raise LayoutChanged("No calendar PDF links found; capture a current court fixture")
        found = set()
        for url in dict.fromkeys(urls):
            _, text = self.pdf(url)
            found.update(calendar_cases(text))
        return sorted(found), urls

    def notices(self, case):
        self.goto(NYSCEF)
        guest = self.page.get_by_role('link', name='Search as Guest', exact=True)
        if guest.count():
            guest.click()
            self.guard()
        courts = self.page.locator('select').filter(has=self.page.locator('option', has_text=re.compile('Queens.*Supreme', re.I)))
        if courts.count() != 1:
            raise LayoutChanged("NYSCEF court selector not found")
        option = courts.locator('option').filter(has_text=re.compile('Queens.*Supreme', re.I)).first
        courts.select_option(option.get_attribute('value'))
        field = self.page.get_by_label(re.compile('Index (?:Number|No)', re.I))
        if field.count() != 1:
            raise LayoutChanged("NYSCEF index search field not found")
        field.fill(case)
        self.page.get_by_role('button', name=re.compile('^Search$', re.I)).click()
        self.guard()
        links = []
        for row in self.page.locator('tr').all():
            if case in indices(row.inner_text()) and re.search('Mortgage Foreclosure', row.inner_text(), re.I):
                for link in row.locator('a[href]').all():
                    if case in indices(link.inner_text()):
                        links.append(urljoin(self.page.url, link.get_attribute('href')))
        if not links:
            if re.search('no (?:records|results|cases) found', self.page.inner_text('body'), re.I):
                return []
            raise LayoutChanged("No uniquely matched Queens mortgage foreclosure case")
        if len(set(links)) != 1:
            raise LayoutChanged("Ambiguous case search results")
        self.goto(links[0])
        docs = self.page.get_by_role('link', name=re.compile('^(Document List|Documents)$', re.I))
        if docs.count():
            docs.first.click()
            self.guard()
        results, seen = [], set()
        for _ in range(100):
            signature = digest(self.page.content().encode())
            if signature in seen:
                raise LayoutChanged("Repeated document pagination page")
            seen.add(signature)
            for row in self.page.locator('tr').all():
                if re.search(r'\bNOTICE\s+OF\s+(?:FORECLOSURE\s+)?SALE\b', row.inner_text(), re.I):
                    links = row.locator('a[href]').all()
                    targets = [urljoin(self.page.url, a.get_attribute('href')) for a in links
                               if re.search(r'ViewDocument|\.pdf\b', a.get_attribute('href') or '', re.I)]
                    if not targets:
                        raise LayoutChanged("Notice row has no document link")
                    results.extend(targets)
            nxt = self.page.get_by_role('link', name=re.compile(r'^(Next|>>|Next >)$', re.I))
            if not nxt.count():
                return list(dict.fromkeys(results))
            nxt.first.click()
            self.guard()
        raise LayoutChanged("Document pagination exceeded limit")
