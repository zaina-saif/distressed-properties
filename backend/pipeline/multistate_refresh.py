"""Multi-state Sale Refresh: the recurring refresh for every state outside NJ.

Stages, in order:
  scrape   Each source's scraper (RealAuction OH/FL, CivilView DE/PA/IL/TX/GA,
           PA county portals, SC Master-in-Equity, Illinois TJSC, NY Erie
           sheriff and NYC tax-lien referee sales). A source that fails is
           reported; the others still run.
  load     Load whatever snapshots were written. A county whose scrape failed
           has no new snapshot, so its open sales are left untouched. NY court
           referee auctions are loaded by hand (the court sites block scripts)
           and the NY county pages drop sales without a result, so their passed
           dates are marked here.
  zillow   Look up Zestimates on Apify for scheduled properties that lack one,
           state by state, never submitting more than --max-zillow-addresses
           in total, then Queens houses the first pass missed, searched again
           without the hyphen and with the town (once per property). NY listings
           with a ZIP but no coordinates are geocoded first.
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

STATES = ("OH", "FL", "IN", "PA", "IL", "SC", "DE", "CO", "MN", "LA", "IA", "WA", "KS", "ID", "OR", "AZ", "AR", "CT", "TX", "KY", "OK", "WI", "SD", "NY")
STAGES = ("scrape", "load", "zillow", "score", "report")
PA_PORTAL_COUNTIES = ["Butler", "Centre", "Cumberland", "Franklin", "Greene", "Lancaster", "Luzerne", "Susquehanna"]
# (name, scrape command, load command); commands run as `python -m <args>` from backend/.
SOURCES = [
    # Ohio and Florida look back two weeks so results of sales held since the last run are loaded.
    ("Ohio RealAuction", ["pipeline.scrape_realauction", "--state", "OH", "--all", "--lookback-days", "14"],
     ["pipeline.load_realauction_sales", "--state", "OH", "--all"]),
    ("Florida RealAuction", ["pipeline.scrape_realauction", "--state", "FL", "--all", "--lookback-days", "14"],
     ["pipeline.load_realauction_sales", "--state", "FL", "--all"]),
    ("Colorado RealAuction", ["pipeline.scrape_realauction", "--state", "CO", "--all"],
     ["pipeline.load_realauction_sales", "--state", "CO", "--all"]),
    ("Indiana SRI sheriff sales", ["pipeline.scrape_sri", "--all", "--lookback-days", "14"],
     ["pipeline.load_sri_sales", "--all"]),
    ("Texas RealAuction tax sales", ["pipeline.scrape_realauction", "--state", "TX", "--all"],
     ["pipeline.load_realauction_sales", "--state", "TX", "--all"]),
    ("CivilView (DE, PA, IL, CO, MN, LA, IA, WA, KS, ID, OR, AZ, AR, TX, GA)", ["pipeline.scrape_civilview_states", "--all"],
     ["pipeline.load_civilview_states", "--all"]),
    # Monroe's Bid4Assets page answers Access Denied, so it is left out.
    ("PA county portals", ["pipeline.scrape_pa_sale_listing", "--counties", *PA_PORTAL_COUNTIES],
     ["pipeline.load_pa_sales", "--counties", *PA_PORTAL_COUNTIES]),
    ("SC Master-in-Equity", ["pipeline.scrape_sc_master_in_equity", "--all"],
     ["pipeline.load_sc_master_in_equity", "--all"]),
    ("Illinois TJSC", ["pipeline.scrape_tjsc_upcoming_sales"], ["pipeline.load_tjsc_upcoming_sales"]),
    ("Connecticut court sales", ["pipeline.scrape_ct_foreclosure_sales"], ["pipeline.load_ct_foreclosure_sales"]),
    ("County sale lists (KY Jefferson, OK Oklahoma/Tulsa, SD Minnehaha, WI Dane/Milwaukee)", ["pipeline.scrape_county_sale_lists", "--all"],
     ["pipeline.load_county_sale_lists", "--all"]),
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
            result = subprocess.run([sys.executable, "-m", *module_args], cwd=BACKEND,
                                    stdout=log, stderr=subprocess.STDOUT, env=os.environ.copy())
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

    def zillow(self) -> None:
        import pipeline.apify_scheduled_zillow as apify
        from pipeline.persist_apify_zillow import persist

        if not os.environ.get("APIFY_API_TOKEN"):
            self.report["failures"].append({"stage": "zillow", "item": "token", "error": "APIFY_API_TOKEN is not set"})
            print("  ! zillow: APIFY_API_TOKEN is not set", flush=True)
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
