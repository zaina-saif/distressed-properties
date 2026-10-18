"""Every other state's sources, mirroring multistate_refresh.SOURCES so each can also
run for one state or one county."""
from pipeline.scrape_civilview_states import COUNTIES as CIVILVIEW_COUNTIES
from pipeline.scrape_county_sale_lists import COUNTIES as COUNTY_LISTS
from pipeline.scrape_realauction import SOURCES as REALAUCTION
from pipeline.scrape_sc_master_in_equity import COUNTIES as SC_COUNTIES
from pipeline.scraping.base import CommandScraper, register


def by_state(keys):
    states: dict[str, list[str]] = {}
    for state, county in keys:
        states.setdefault(state, []).append(county)
    return states


# RealAuction: OH sheriff, FL clerk, CO Public Trustee, TX tax sales. OH and FL look back
# two weeks so results of sales held since the last run are loaded.
for state, counties in sorted(REALAUCTION.items()):
    lookback = ["--lookback-days", "14"] if state in ("OH", "FL") else []
    register(CommandScraper(
        name=f"{state.lower()}-realauction", state=state, counties=sorted(counties),
        scrape=lambda selected, ctx, state=state, lookback=lookback: ["pipeline.scrape_realauction", "--state", state]
        + (["--counties", *selected] if selected else ["--all"]) + lookback,
        load=lambda selected, ctx, state=state: ["pipeline.load_realauction_sales", "--state", state]
        + (["--counties", *selected] if selected else ["--all"]),
    ))

for state, counties in sorted(by_state(CIVILVIEW_COUNTIES).items()):
    register(CommandScraper(
        name=f"{state.lower()}-civilview", state=state, counties=sorted(counties),
        scrape=lambda selected, ctx, state=state: ["pipeline.scrape_civilview_states"]
        + (["--counties", *[f"{state}:{county}" for county in selected]] if selected else ["--state", state]),
        load=lambda selected, ctx, state=state: ["pipeline.load_civilview_states"]
        + (["--counties", *[f"{state}:{county}" for county in selected]] if selected else ["--state", state]),
    ))

for state, counties in sorted(by_state(COUNTY_LISTS).items()):
    register(CommandScraper(
        name=f"{state.lower()}-county-sale-lists", state=state, counties=sorted(counties),
        scrape=lambda selected, ctx, state=state, counties=counties: ["pipeline.scrape_county_sale_lists", "--counties",
                                                                      *[f"{state}:{c}" for c in (selected or counties)]],
        load=lambda selected, ctx, state=state, counties=counties: ["pipeline.load_county_sale_lists", "--counties",
                                                                    *[f"{state}:{c}" for c in (selected or counties)]],
    ))

# Indiana counties come from SRI's own list, so any county name is passed through.
register(CommandScraper(
    name="in-sri", state="IN", counties=["*"],
    scrape=lambda selected, ctx: ["pipeline.scrape_sri", "--lookback-days", "14"]
    + (["--counties", *selected] if selected else ["--all"]),
    load=lambda selected, ctx: ["pipeline.load_sri_sales"] + (["--counties", *selected] if selected else ["--all"]),
))

register(CommandScraper(
    name="sc-master-in-equity", state="SC", counties=sorted(SC_COUNTIES),
    scrape=lambda selected, ctx: ["pipeline.scrape_sc_master_in_equity"]
    + (["--counties", *selected] if selected else ["--all"]),
    load=lambda selected, ctx: ["pipeline.load_sc_master_in_equity"]
    + (["--counties", *selected] if selected else ["--all"]),
))

register(CommandScraper(
    name="il-tjsc", state="IL", counties=["*"], county_level=False,
    scrape=lambda selected, ctx: ["pipeline.scrape_tjsc_upcoming_sales"],
    load=lambda selected, ctx: ["pipeline.load_tjsc_upcoming_sales"],
))

register(CommandScraper(
    name="ct-court-sales", state="CT", counties=["*"], county_level=False,
    scrape=lambda selected, ctx: ["pipeline.scrape_ct_foreclosure_sales"],
    load=lambda selected, ctx: ["pipeline.load_ct_foreclosure_sales"],
))

# Texas trustee-sale notices from the Harris County Clerk (scanned PDFs read with macOS OCR,
# so this runs on the operator's Mac, not in the scheduled refresh).
register(CommandScraper(
    name="tx-harris-trustee-notices", state="TX", counties=["Harris"],
    scrape=lambda selected, ctx: ["pipeline.scrape_harris_trustee_notices"],
    load=lambda selected, ctx: ["pipeline.load_tx_trustee_sales"],
))

# Texas trustee-sale notices from the Bexar County Clerk's foreclosure map (ArcGIS service).
register(CommandScraper(
    name="tx-bexar-trustee-notices", state="TX", counties=["Bexar"],
    scrape=lambda selected, ctx: ["pipeline.scrape_bexar_trustee_notices"],
    load=lambda selected, ctx: ["pipeline.load_tx_trustee_sales", "--input",
                                "data/sheriff_sales/tx_bexar_trustee_notices.json"],
))

# Texas trustee-sale notices from the Collin County Clerk's foreclosure notices site (headless browser).
register(CommandScraper(
    name="tx-collin-trustee-notices", state="TX", counties=["Collin"],
    scrape=lambda selected, ctx: ["pipeline.scrape_collin_trustee_notices"],
    load=lambda selected, ctx: ["pipeline.load_tx_trustee_sales", "--input",
                                "data/sheriff_sales/tx_collin_trustee_notices.json"],
))

# Texas trustee-sale notices from the Fort Bend County Clerk's monthly list (scanned PDF read
# with macOS OCR, so this runs on the operator's Mac, not in the scheduled refresh).
register(CommandScraper(
    name="tx-fort-bend-trustee-notices", state="TX", counties=["Fort Bend"],
    scrape=lambda selected, ctx: ["pipeline.scrape_fort_bend_trustee_notices"],
    load=lambda selected, ctx: ["pipeline.load_tx_trustee_sales", "--input",
                                "data/sheriff_sales/tx_fort_bend_trustee_notices.json"],
))

# California county tax-defaulted property sales on Bid4Assets (every CA sale on its calendar).
register(CommandScraper(
    name="ca-bid4assets-tax-sales", state="CA", counties=["*"], county_level=False,
    scrape=lambda selected, ctx: ["pipeline.scrape_ca_tax_sales"],
    load=lambda selected, ctx: ["pipeline.load_ca_tax_sales"],
))
