"""Importing this package registers every scraper plugin (one module per state group)."""
from pipeline.scraping.plugins import nj, ny, other_states, pa  # noqa: F401
