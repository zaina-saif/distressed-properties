"""Recognise a page that is an active verification challenge or block.

Only interstitials and blocking pages count. A normal page that merely loads a
CAPTCHA library for one of its forms (an invisible hCaptcha on a search button,
a reCAPTCHA badge) is not a challenge: flagging those is what kept the first
Queens collector waiting after the operator had already passed.
"""
import re

from bs4 import BeautifulSoup


class AccessChallenge(RuntimeError):
    """The site asked for human verification or refused access; nothing was imported."""

    def __init__(self, message: str, kind: str | None = None, url: str | None = None):
        super().__init__(message)
        self.kind, self.url = kind, url


# Titles of interstitial and block pages served instead of the content.
CHALLENGE_TITLES = [
    (re.compile(r"just a moment|attention required|checking your browser|one more step", re.I), "cloudflare"),
    (re.compile(r"^\s*access denied\s*$|403\W*forbidden|request blocked|you have been blocked", re.I), "access_denied"),
    (re.compile(r"verify(?:ing)? you are (?:a )?human|are you a robot|security check|captcha", re.I), "captcha"),
    (re.compile(r"pardon our interruption", re.I), "bot_protection"),
]
# Markup only present on challenge or block pages. Cloudflare and Incapsula also inject
# scripts into ordinary pages (/cdn-cgi/challenge-platform/, _Incapsula_Resource), so
# those paths are not used.
CHALLENGE_MARKUP = [
    (re.compile(r"\bcf-chl-[a-z]|cf_chl_opt", re.I), "cloudflare"),
    (re.compile(r"errors\.edgesuite\.net", re.I), "access_denied"),
    (re.compile(r"Incapsula incident ID|geo\.captcha-delivery\.com", re.I), "bot_protection"),
]
VISIBLE_PROMPTS = re.compile(
    r"verify you are (?:a )?human|complete the security check|please complete the captcha|"
    r"unusual traffic from your|press (?:and|&) hold|enable javascript and cookies to continue", re.I)
# Little visible text besides the prompt marks an interstitial, not a content page.
INTERSTITIAL_MAX_TEXT = 1500


def visible_text(soup: BeautifulSoup) -> str:
    for node in soup(["script", "style", "noscript", "template"]):
        node.decompose()
    return " ".join(soup.get_text(" ", strip=True).split())


def detect_challenge(html: str, status: int | None = None, title: str | None = None) -> str | None:
    """The kind of challenge ('cloudflare', 'captcha', 'access_denied', 'bot_protection'),
    or None for an ordinary page."""
    html = html or ""
    soup = BeautifulSoup(html, "html.parser")
    title = title if title is not None else (soup.title.get_text(" ", strip=True) if soup.title else "")
    for pattern, kind in CHALLENGE_TITLES:
        if title and pattern.search(title):
            return kind
    for pattern, kind in CHALLENGE_MARKUP:
        if pattern.search(html):
            return kind
    text = visible_text(soup)
    if VISIBLE_PROMPTS.search(text) and len(text) <= INTERSTITIAL_MAX_TEXT:
        return "captcha"
    if status in (401, 403) and len(text) <= INTERSTITIAL_MAX_TEXT:
        return "access_denied"
    if status == 429:
        return None  # rate limited: a retry with backoff, not a verification
    return None
