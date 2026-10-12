"""Shared scraping framework: polite HTTP, operator-assisted browser sessions,
monitoring artifacts and a registry of scrapers (see pipeline.cli).

Collectors never solve CAPTCHAs or get past access controls. When a site shows a
verification challenge, a visible browser waits for the operator to complete it;
unattended runs stop with AccessChallenge and import nothing.
"""
from pipeline.scraping.challenge import AccessChallenge, detect_challenge

__all__ = ["AccessChallenge", "detect_challenge"]
