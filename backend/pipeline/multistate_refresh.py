"""Multi-state Sale Refresh: the recurring refresh for every state outside NJ.

Stages, in order:
  scrape   Each source's scraper (RealAuction OH/FL/TX, CivilView PA/IL/TX/AZ/GA,
           PA county portals, Illinois TJSC, TX trustee notices, CA and NV tax
           sales, NC foreclosure and tax foreclosure lists, NY Erie sheriff and
           NYC tax-lien referee sales), phase 1 states only.
           A source that fails is reported; the others still run.
  load     Load whatever snapshots were written. A county whose scrape failed
           has no new snapshot, so its open sales are left untouched. NY court
           referee auctions are loaded by hand (the court sites block scripts)
           and the NY county pages drop sales without a result, so their passed
           dates are marked here. The report shows, per NY court county (Queens,
           New York), the open listings, the next auction and when the court
           files were last loaded, since only a new load brings new dates.
  zillow   Look up Zestimates on Apify for scheduled properties that lack one,
           state by state, never submitting more than --max-zillow-addresses
           in total, then Queens houses the first pass missed, searched again
           without the hyphen and with the town (once per property). NY listings
           with a ZIP but no coordinates are geocoded first; NYC listings still
           without a Zestimate then get the city's DOF market value
           (pipeline.load_nyc_dof_values).
  score    Re-score probability to auction with the saved model.
  report   Counts per state, written to report.json.

Scraper and loader output (which includes addresses) goes to
<run-dir>/refresh.log, so CI logs only carry counts.

    python -m pipeline.multistate_refresh --run-dir /tmp/refresh --max-zillow-addresses 600
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.database.session import engine
from pipeline.scrape_civilview_states import COUNTIES as CIVILVIEW_COUNTIES

# Phase 1 states outside NJ (October 2026; see SUPPORTED_STATES in app/auth.py). Indiana,
# Colorado, South Carolina, Connecticut and the county-list states (KY, OK, SD, WI) are no
# longer refreshed or sent to Zillow; their listings stay in the database, hidden. GA
# and NV are collected (CivilView Coweta; Bid4Assets and Clark County tax sales) so they can be shown once they have
# upcoming listings.
STATES = ("OH", "FL", "PA", "IL", "TX", "NY", "CA", "AZ", "GA", "NC", "NV")
CIVILVIEW = [f"{state}:{county}" for state, county in sorted(CIVILVIEW_COUNTIES) if state in STATES]
STAGES = ("scrape", "load", "zillow", "score", "report")
PA_PORTAL_COUNTIES = ["Butler", "Centre", "Cumberland", "Franklin", "Greene", "Lancaster", "Luzerne", "Susquehanna"]
# (name, scrape command, load command); commands run as `python -m <args>` from backend/.
SOURCES = [
    # Ohio and Florida look back two weeks so results of sales held since the last run are loaded.
    ("Ohio RealAuction", ["pipeline.scrape_realauction", "--state", "OH", "--all", "--lookback-days", "14"],
     ["pipeline.load_realauction_sales", "--state", "OH", "--all"]),
    ("Florida RealAuction", ["pipeline.scrape_realauction", "--state", "FL", "--all", "--lookback-days", "14"],
     ["pipeline.load_realauction_sales", "--state", "FL", "--all"]),
    ("Texas RealAuction tax sales", ["pipeline.scrape_realauction", "--state", "TX", "--all"],
     ["pipeline.load_realauction_sales", "--state", "TX", "--all"]),
    ("CivilView (PA, IL, TX, AZ, GA)", ["pipeline.scrape_civilview_states", "--counties", *CIVILVIEW],
     ["pipeline.load_civilview_states", "--counties", *CIVILVIEW]),
    # Monroe's Bid4Assets page answers Access Denied, so it is left out.
    ("PA county portals", ["pipeline.scrape_pa_sale_listing", "--counties", *PA_PORTAL_COUNTIES],
     ["pipeline.load_pa_sales", "--counties", *PA_PORTAL_COUNTIES]),
    ("Illinois TJSC", ["pipeline.scrape_tjsc_upcoming_sales"], ["pipeline.load_tjsc_upcoming_sales"]),
    ("TX Bexar trustee-sale notices", ["pipeline.scrape_bexar_trustee_notices"],
     ["pipeline.load_tx_trustee_sales", "--input", "data/sheriff_sales/tx_bexar_trustee_notices.json"]),
    ("TX Collin trustee-sale notices", ["pipeline.scrape_collin_trustee_notices"],
     ["pipeline.load_tx_trustee_sales", "--input", "data/sheriff_sales/tx_collin_trustee_notices.json"]),
    ("California county tax sales (Bid4Assets)", ["pipeline.scrape_ca_tax_sales"], ["pipeline.load_ca_tax_sales"]),
    ("Nevada county tax sales (Bid4Assets)", ["pipeline.scrape_ca_tax_sales", "--state", "NV"],
     ["pipeline.load_ca_tax_sales", "--state", "NV"]),
    ("NV Clark County treasurer tax auction", ["pipeline.scrape_nv_clark_tax_auction"],
     ["pipeline.load_nv_clark_tax_auction"]),
    ("GA DeKalb County tax sales", ["pipeline.scrape_ga_dekalb_tax_sales"],
     ["pipeline.load_ga_tax_sales", "--input", "data/sheriff_sales/ga_dekalb_tax_sales.json"]),
    ("NC foreclosure sales (Hutchens Law Firm)", ["pipeline.scrape_nc_hutchens_sales"], ["pipeline.load_nc_hutchens_sales"]),
    ("NC tax foreclosure sales (Zacchaeus Legal Services)", ["pipeline.scrape_nc_zls_tax_foreclosures"],
     ["pipeline.load_nc_zls_tax_foreclosures"]),
    # Orange County's page answers 403, so only Erie is scraped.
    ("NY Erie sheriff sales", ["pipeline.scrape_ny_county_pages", "--counties", "Erie"],
     ["pipeline.load_ny_sales", "--counties", "Erie"]),
    ("NYC tax-lien referee sales", ["pipeline.scrape_nyc_referee_sales"], ["pipeline.load_nyc_referee_sales"]),
]
# Sources whose loaders never retire a passed date: NY court auctions are loaded by hand
# (pipeline.load_ny_court_pdfs, pipeline.load_queens_pipeline), and the NY county sheriff
# pages drop a sale without a result (Orange's page is no longer reachable at all).
UNRETIRED_SOURCES = ("ny_court_foreclosure_auction", "ny_county_official")
BACKEND = Path(__file__).resolve().parents[1]
# One source may not use the whole run: Philadelphia's CivilView details once retried for
# hours after the site dropped the session, and the workflow's 4-hour limit cancelled
# every Monday run in the scrape stage. A source over this is stopped, reported, and
# keeps its previous snapshot.
SOURCE_TIMEOUT_SECONDS = 40 * 60
DEFAULT_RUN_ROOT = BACKEND.parent / ".local" / "multistate-refresh"


def scheduled_counts() -> dict[str, dict[str, int]]:
    with engine.connect() as connection:
        rows = connection.execute(text("""
            SELECT ss.state, COUNT(*) AS scheduled,
                   COUNT(*) FILTER (WHERE EXISTS (SELECT 1 FROM apify_zillow_results z
                       WHERE z.property_id=ss.property_id AND z.is_current AND z.zestimate IS NOT NULL)) AS with_zestimate
            FROM sheriff_sales ss
            WHERE ss.state = ANY(:states) AND strpos(lower(ss.current_status),'scheduled')>0
            GROUP BY ss.state
        """), {"states": list(STATES)}).mappings().all()
    return {row["state"]: {"scheduled": int(row["scheduled"]), "with_zestimate": int(row["with_zestimate"])}
            for row in rows}


def retire_passed_listings() -> int:
    """A listing from UNRETIRED_SOURCES still 'scheduled' after its date has no published
    result: it becomes sold_or_cancelled_unverified until a load brings the outcome."""
    with engine.begin() as connection:
        ids = connection.execute(text("""UPDATE sheriff_sales SET current_status='sold_or_cancelled_unverified',
            updated_at=NOW() WHERE source_system = ANY(:sources) AND current_status='scheduled'
            AND current_sale_date::date < CURRENT_DATE RETURNING id, current_sale_date, source_url"""),
            {"sources": list(UNRETIRED_SOURCES)}).all()
        for sale_id, sale_date, url in ids:
            connection.execute(text("""INSERT INTO sheriff_sale_status_history(id,sheriff_sale_id,status,sale_date,
                observed_at,source_url,raw_status) VALUES(:history_id,:id,'sold_or_cancelled_unverified',
                :sale_date,NOW(),:url,'Auction date passed; result not published')"""),
                {"history_id": str(uuid.uuid4()), "id": sale_id, "sale_date": sale_date, "url": url})
    return len(ids)


def ny_court_counties() -> dict[str, dict[str, Any]]:
    """Per county of hand-loaded NY court auctions (Queens, New York): open listings, the
    next auction, and the day the court files were last loaded (pipeline.load_queens_pipeline),
    so the report shows when a county needs its new calendar and case files."""
    with engine.connect() as connection:
        rows = connection.execute(text("""
            SELECT ss.county,
                   COUNT(*) FILTER (WHERE ss.current_status IN ('scheduled', 'adjourned')) AS open,
                   MIN(ss.current_sale_date::date) FILTER (WHERE ss.current_status = 'scheduled'
                       AND ss.current_sale_date::date >= CURRENT_DATE) AS next_auction,
                   MAX(cs.updated_at)::date AS files_loaded
            FROM sheriff_sales ss JOIN ny_court_case_summaries cs ON cs.sheriff_sale_id = ss.id
            WHERE ss.source_system = 'ny_court_foreclosure_auction'
            GROUP BY ss.county ORDER BY ss.county""")).mappings().all()
    return {row["county"]: {"open": row["open"], "next_auction": str(row["next_auction"]) if row["next_auction"] else None,
                            "files_loaded": str(row["files_loaded"])} for row in rows}


class Refresh:
    def __init__(self, run_dir: Path, max_zillow_addresses: int) -> None:
        self.run_dir = run_dir
        self.max_zillow_addresses = max_zillow_addresses
        self.log_path = run_dir / "refresh.log"
        self.report: dict[str, Any] = {"pipeline": "multistate_refresh",
                                       "started_at": datetime.now(timezone.utc).isoformat(),
                                       "stages": {}, "failures": []}

    def _run(self, stage: str, name: str, module_args: list[str]) -> bool:
        with self.log_path.open("a", encoding="utf-8") as log:
            log.write(f"\n===== {stage}: {name}: {' '.join(module_args)}\n")
            log.flush()
            try:
                result = subprocess.run([sys.executable, "-m", *module_args], cwd=BACKEND, stdout=log,
                                        stderr=subprocess.STDOUT, env=os.environ.copy(), timeout=SOURCE_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                log.write(f"\n[{stage}] {name}: stopped after {SOURCE_TIMEOUT_SECONDS // 60} minutes\n")
                self.report["failures"].append({"stage": stage, "item": name, "error": "timed out"})
                print(f"  ! {stage} {name}: timed out after {SOURCE_TIMEOUT_SECONDS // 60} minutes", flush=True)
                return False
        if result.returncode:
            self.report["failures"].append({"stage": stage, "item": name, "exit_code": result.returncode})
            print(f"  ! {stage} {name}: exit {result.returncode}", flush=True)
        else:
            print(f"  {stage} {name}: ok", flush=True)
        return result.returncode == 0

    def scrape(self) -> None:
        # Scrapers that fail for some counties still keep the others' snapshots.
        self.report["stages"]["scrape"] = {name: self._run("scrape", name, args) for name, args, _ in SOURCES}

    def load(self) -> None:
        self.report["stages"]["load"] = {name: self._run("load", name, args) for name, _, args in SOURCES}
        # Winning bids and buyers for sales the loaders just marked sold (e.g. Ohio).
        self.report["stages"]["sale_results"] = {"ok": self._run("load", "sale results", ["pipeline.sale_results"])}
        self.report["stages"]["ny_dates_passed"] = retire_passed_listings()
        print(f"  load NY listings past their date: {self.report['stages']['ny_dates_passed']}", flush=True)
        self.flag_timeshares()
        try:
            self.report["stages"]["ny_court_counties"] = ny_court_counties()
            print(f"  NY court listings: {self.report['stages']['ny_court_counties']}", flush=True)
        except Exception as exc:  # noqa: BLE001 - a report line only
            self.report["failures"].append({"stage": "load", "item": "ny_court_counties", "error": f"{type(exc).__name__}: {exc}"})

    def flag_timeshares(self) -> None:
        """Timeshare listings are not valued (pipeline.flag_timeshares); before the Zillow stage."""
        from pipeline.flag_timeshares import flag
        try:
            self.report["stages"]["timeshares"] = flag()
            print(f"  timeshares marked not valued: {self.report['stages']['timeshares']}", flush=True)
        except Exception as exc:  # noqa: BLE001 - the refresh goes on
            self.report["failures"].append({"stage": "load", "item": "flag_timeshares", "error": f"{type(exc).__name__}: {exc}"})

    def zillow(self) -> None:
        import pipeline.apify_scheduled_zillow as apify
        from pipeline.persist_apify_zillow import persist

        if not os.environ.get("APIFY_API_TOKEN"):
            self.report["failures"].append({"stage": "zillow", "item": "token", "error": "APIFY_API_TOKEN is not set"})
            print("  ! zillow: APIFY_API_TOKEN is not set", flush=True)
            self.nyc_values()
            return
        remaining = self.max_zillow_addresses
        stage: dict[str, Any] = {}
        # Zillow rarely matches an address without a ZIP; fill missing ones first (free Census geocoder).
        try:
            from pipeline.fill_missing_zips import fill
            with self.log_path.open("a", encoding="utf-8") as log:
                with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                    stage["zip_lookup"] = fill(list(STATES))
                    # NY court listings arrive with a ZIP but no coordinates.
                    stage["ny_coordinates"] = fill(["NY"], coordinates=True)
            print(f"  zip lookup: {stage['zip_lookup']}; NY coordinates: {stage['ny_coordinates']}", flush=True)
        except Exception as exc:  # noqa: BLE001 - Zillow still runs without the ZIPs
            self.report["failures"].append({"stage": "zillow", "item": "zip_lookup", "error": f"{type(exc).__name__}: {exc}"})
        # Each state's first pass, then a second search for Queens houses the first pass missed
        # (Zillow lists many without the hyphen and with the town; see queens_retry_address).
        batches = [(state, state, {"only_missing": True}) for state in STATES]
        batches.append(("NY Queens retry", "NY", {"queens_retry": True}))
        for name, state, options in batches:
            apify.OUTPUT = self.run_dir / f"zillow-{name.lower().replace(' ', '-')}"
            apify.TARGET_STATE = state
            try:
                with self.log_path.open("a", encoding="utf-8") as log:
                    with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                        apify.prepare(**options)
                        addresses = json.loads((apify.OUTPUT / "input.json").read_text())["addresses"]
                        if not addresses:
                            stage[name] = {"submitted": 0}
                            continue
                        if len(addresses) > remaining:
                            stage[name] = {"skipped": f"{len(addresses)} addresses exceeds the remaining cap of {remaining}"}
                            continue
                        apify.EXPECTED_COUNT = str(len(addresses))
                        apify.submit()
                        apify.watch()
                        result = persist(apify.OUTPUT)
                remaining -= len(addresses)
                stage[name] = {"submitted": len(addresses), "matched": result["matched"], "no_match": result["no_match"]}
            except Exception as exc:  # noqa: BLE001 - one state's run must not stop the others
                self.report["failures"].append({"stage": "zillow", "item": name, "error": f"{type(exc).__name__}: {exc}"})
                with self.log_path.open("a", encoding="utf-8") as log:
                    log.write(f"\n[zillow] {name} failed\n{traceback.format_exc()}\n")
            print(f"  zillow {name}: {stage.get(name, 'failed')}", flush=True)
        self.report["stages"]["zillow"] = stage
        self.nyc_values()

    def nyc_values(self) -> None:
        """NYC listings Zillow has no Zestimate for: the DOF market value (free NYC Open Data)."""
        from pipeline.load_nyc_dof_values import fill
        try:
            with self.log_path.open("a", encoding="utf-8") as log:
                log.write("\n===== zillow: NYC DOF market values\n")
                with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                    result = fill()
            self.report["stages"]["nyc_dof_values"] = result
            print(f"  NYC DOF values: {result}", flush=True)
        except Exception as exc:  # noqa: BLE001 - the values are optional; the refresh goes on
            self.report["failures"].append({"stage": "zillow", "item": "nyc_dof_values", "error": f"{type(exc).__name__}: {exc}"})
            print(f"  ! NYC DOF values: {type(exc).__name__}", flush=True)

    def score(self) -> None:
        import joblib

        from pipeline.train_sale_probability_model import ARTIFACT_PATH, MODEL_VERSION, _load_db_rows, score_current

        try:
            artifact = joblib.load(ARTIFACT_PATH)
            sales, histories = _load_db_rows()
            count = score_current(artifact["model"], sales, histories, artifact["feature_columns"],
                                  artifact.get("typical"), artifact.get("metrics"))
            self.report["stages"]["score"] = {"model_version": MODEL_VERSION, "scored": count}
            print(f"  scored {count} scheduled sales", flush=True)
        except Exception as exc:  # noqa: BLE001
            self.report["failures"].append({"stage": "score", "item": "sale_probability", "error": f"{type(exc).__name__}: {exc}"})

    def report_stage(self) -> None:
        self.report["finished_at"] = datetime.now(timezone.utc).isoformat()
        self.report["scheduled_by_state"] = scheduled_counts()
        (self.run_dir / "report.json").write_text(json.dumps(self.report, indent=2) + "\n")
        for state, counts in sorted(self.report["scheduled_by_state"].items()):
            print(f"  {state}: {counts}", flush=True)


def write_summary(report: dict[str, Any]) -> None:
    """Append a Markdown summary to the GitHub Actions job page when running there."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = ["## Multi-state Sale Refresh", "", "| State | Scheduled | With Zestimate |", "|---|---|---|"]
    for state, counts in sorted(report.get("scheduled_by_state", {}).items()):
        lines.append(f"| {state} | {counts['scheduled']} | {counts['with_zestimate']} |")
    if report.get("stages", {}).get("zillow"):
        lines += ["", f"**Zillow:** {report['stages']['zillow']}"]
    if report["failures"]:
        lines += ["", "**Failures:**"] + [f"- {item}" for item in report["failures"]]
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stages", nargs="+", choices=STAGES, default=list(STAGES))
    parser.add_argument("--skip-zillow", action="store_true", help="Skip the paid Apify Zillow stage")
    parser.add_argument("--max-zillow-addresses", type=int, default=600,
                        help="Never submit more than this many addresses to Apify in one run (cost guard)")
    parser.add_argument("--run-dir", type=Path, help="Working directory for Apify files, the log and report.json")
    args = parser.parse_args()
    run_dir = args.run_dir or DEFAULT_RUN_ROOT / datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    refresh = Refresh(run_dir, args.max_zillow_addresses)
    stages = [stage for stage in STAGES if stage in args.stages and not (stage == "zillow" and args.skip_zillow)]
    for stage in stages:
        print(f"== {stage}", flush=True)
        getattr(refresh, "report_stage" if stage == "report" else stage)()
    write_summary(refresh.report)
    if refresh.report["failures"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
