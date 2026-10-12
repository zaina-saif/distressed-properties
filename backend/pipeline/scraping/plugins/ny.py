"""New York: county sheriff pages, NYC referee tax-lien sales, court auction PDFs
saved by the operator, and the operator-assisted Queens collector.

    python main.py scrape ny
    python main.py scrape county "erie"
    python main.py scrape county "queens" --assisted
"""
import os

from pipeline.scrape_ny_county_pages import SOURCES as NY_COUNTY_PAGES
from pipeline.scraping.base import CommandScraper, register

NYC = ["Bronx", "Kings", "New York", "Queens", "Richmond"]


def court_pdf_folder() -> str:
    folder = os.environ.get("NY_COURT_PDF_FOLDER")
    if not folder:
        raise ValueError("Set NY_COURT_PDF_FOLDER to the folder of saved court PDFs (see AGENTS.md, New York pipeline)")
    return os.path.expanduser(folder)


register(CommandScraper(
    name="ny-county-sheriff-pages", state="NY", counties=sorted(NY_COUNTY_PAGES),
    scrape=lambda counties, ctx: ["pipeline.scrape_ny_county_pages"] + (["--counties", *counties] if counties else ["--all"]),
    load=lambda counties, ctx: ["pipeline.load_ny_sales"] + (["--counties", *counties] if counties else ["--all"]),
))

register(CommandScraper(
    name="nyc-referee-tax-lien-sales", state="NY", counties=NYC, county_level=False,
    scrape=lambda counties, ctx: ["pipeline.scrape_nyc_referee_sales"],
    load=lambda counties, ctx: ["pipeline.load_nyc_referee_sales"],
))

register(CommandScraper(
    name="ny-court-auction-pdfs", state="NY", counties=["Kings", "Bronx", "New York"],
    # Statewide runs include it only when the operator has a PDF folder configured.
    statewide=bool(os.environ.get("NY_COURT_PDF_FOLDER")),
    scrape=lambda counties, ctx: ["pipeline.load_ny_court_pdfs", "--folder", court_pdf_folder()]
    + (["--dry-run"] if ctx.dry_run else []),
))

register(CommandScraper(
    name="ny-queens-webcivil-nyscef", state="NY", counties=["Queens"], statewide=False, requires_browser=True,
    scrape=lambda counties, ctx: ["pipeline.queens_foreclosure_refresh"]
    + (["--assisted"] if ctx.assisted else []) + (["--dry-run"] if ctx.dry_run else []),
))
