"""New Jersey: the full NJ refresh for the state, CivilView county by county otherwise.

    python main.py scrape nj
    python main.py scrape county "bergen"
"""
from pipeline.scrape_nj_civilview import CIVILVIEW_COUNTIES
from pipeline.scraping.base import CommandScraper, register

NJ_COUNTIES = sorted(CIVILVIEW_COUNTIES) + ["Ocean"]

register(CommandScraper(
    name="nj-sale-refresh", state="NJ", counties=NJ_COUNTIES, county_level=False,
    # Open and sold/cancelled lists for every county plus Ocean's PDF, then load and link
    # listings to properties; the paid Zillow stage is left to the scheduled refresh.
    scrape=lambda counties, ctx: ["pipeline.nj_sale_refresh", "--skip-zillow", "--stages", "scrape"]
    + ([] if ctx.dry_run else ["load", "link", "score", "report"]),
))

register(CommandScraper(
    name="nj-civilview-county", state="NJ", counties=sorted(CIVILVIEW_COUNTIES), statewide=False,
    scrape=lambda counties, ctx: ["pipeline.scrape_nj_civilview", "--counties", *counties]
    + ([] if ctx.dry_run else ["--load"]),
    after=[["pipeline.create_properties"]],
))
