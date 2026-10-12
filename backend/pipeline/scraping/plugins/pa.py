"""Pennsylvania county sale-listing portals (CivilView counties are in other_states)."""
from pipeline.multistate_refresh import PA_PORTAL_COUNTIES
from pipeline.scraping.base import CommandScraper, register

register(CommandScraper(
    name="pa-county-portals", state="PA", counties=PA_PORTAL_COUNTIES,
    scrape=lambda counties, ctx: ["pipeline.scrape_pa_sale_listing", "--counties", *(counties or PA_PORTAL_COUNTIES)],
    load=lambda counties, ctx: ["pipeline.load_pa_sales", "--counties", *(counties or PA_PORTAL_COUNTIES)],
))
