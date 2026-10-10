"""NJ Sale Refresh: the recurring end-to-end refresh for NJ sheriff sales.

Stages, in order:
  scrape   CivilView open + sold/cancelled history for every NJ county, and
           Ocean County's PDF. A county that fails is reported and skipped.
  load     Load each snapshot into Supabase (open listings before history,
           so the newest status lands last).
  link     Create/link property records for new sales.
  zillow   Look up Zestimates on Apify for scheduled properties that lack
           one, refusing to submit more than --max-zillow-addresses.
  score    Re-score probability to auction with the saved model.
  report   Print counts and write report.json.

Gross equity and gross equity % need no stage: the API derives them from
the current Zestimate and minimum bid at query time.

Per-record output from the underlying scripts (which includes addresses)
goes to <run-dir>/refresh.log rather than the console, so CI logs only
carry counts.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import text

from app.database.session import engine

STAGES = ("scrape", "load", "link", "zillow", "score", "report")
# Burlington publishes no sold/cancelled history on CivilView.
NO_HISTORY_COUNTIES = {"Burlington"}
DEFAULT_RUN_ROOT = Path(__file__).resolve().parents[2] / ".local" / "nj-sale-refresh"


def _slug(county: str) -> str:
    return county.lower().replace(" ", "_")


def snapshot_counts() -> dict[str, Any]:
    with engine.connect() as connection:
        row = connection.execute(text("""
            SELECT
              COUNT(*) AS nj_sales,
              COUNT(*) FILTER (WHERE strpos(lower(ss.current_status),'scheduled')>0) AS scheduled,
              COUNT(*) FILTER (WHERE strpos(lower(ss.current_status),'scheduled')>0
                               AND ss.current_sale_date < CURRENT_DATE) AS scheduled_past_date,
              COUNT(*) FILTER (WHERE strpos(lower(ss.current_status),'scheduled')>0
                               AND ss.property_id IS NULL) AS scheduled_unlinked,
              COUNT(*) FILTER (WHERE strpos(lower(ss.current_status),'scheduled')>0 AND EXISTS (
                  SELECT 1 FROM apify_zillow_results z WHERE z.property_id=ss.property_id
                    AND z.is_current AND z.zestimate IS NOT NULL)) AS scheduled_with_zestimate,
              COUNT(*) FILTER (WHERE strpos(lower(ss.current_status),'scheduled')>0 AND
                  COALESCE(ss.estimated_upset_price, ss.alternate_upset_price, ss.upset_price,
                           ss.judgment_amount) IS NOT NULL) AS scheduled_with_minimum_bid
            FROM sheriff_sales ss WHERE ss.state='NJ'
        """)).mappings().one()
    return {key: int(value) for key, value in row.items()}


class Refresh:
    def __init__(self, run_dir: Path, max_zillow_addresses: int) -> None:
        self.run_dir = run_dir
        self.snapshot_dir = run_dir / "snapshots"
        self.max_zillow_addresses = max_zillow_addresses
        self.log_path = run_dir / "refresh.log"
        self.report: dict[str, Any] = {
            "pipeline": "nj_sale_refresh",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "stages": {},
            "failures": [],
        }
        self.open_files: list[Path] = []
        self.history_files: list[Path] = []

    def _quiet(self, func: Callable[..., Any], *args: Any) -> Any:
        """Run a stage step with its stdout/stderr appended to the run log."""
        with self.log_path.open("a", encoding="utf-8") as log, \
                contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            return func(*args)

    def _fail(self, stage: str, item: str, exc: BaseException) -> None:
        self.report["failures"].append({"stage": stage, "item": item, "error": f"{type(exc).__name__}: {exc}"})
        with self.log_path.open("a", encoding="utf-8") as log:
            log.write(f"\n[{stage}] {item} failed\n{traceback.format_exc()}\n")
        print(f"  ! {stage} {item}: {type(exc).__name__}", flush=True)

    @staticmethod
    def _record_count(path: Path) -> int:
        return len(json.loads(path.read_text(encoding="utf-8")))

    def scrape(self) -> None:
        from pipeline.scrape_nj_civilview import CIVILVIEW_COUNTIES, scrape as scrape_open
        from pipeline.scrape_nj_sold_cancelled import scrape as scrape_history
        from pipeline.scrape_ocean_county import scrape as scrape_ocean

        counts: dict[str, dict[str, int]] = {}
        for county, county_id in sorted(CIVILVIEW_COUNTIES.items()):
            counts[county] = {}
            try:
                path = self._quiet(lambda: asyncio.run(scrape_open(county, county_id, self.snapshot_dir)))
                counts[county]["open"] = self._record_count(path)
                self.open_files.append(path)
            except Exception as exc:  # noqa: BLE001 - one county must not stop the others
                self._fail("scrape", f"{county} open", exc)
            if county not in NO_HISTORY_COUNTIES:
                try:
                    output = self.snapshot_dir / f"{_slug(county)}_sold_cancelled.json"
                    path = self._quiet(lambda: asyncio.run(scrape_history(county, county_id, output, True)))
                    counts[county]["sold_cancelled"] = self._record_count(path)
                    self.history_files.append(path)
                except Exception as exc:  # noqa: BLE001
                    self._fail("scrape", f"{county} sold/cancelled", exc)
            print(f"  {county}: {counts[county]}", flush=True)
        try:
            path = self._quiet(scrape_ocean, self.snapshot_dir / "ocean_all_sheriff_sales.json")
            counts["Ocean"] = {"open": self._record_count(path)}
            self.open_files.append(path)
            print(f"  Ocean: {counts['Ocean']}", flush=True)
        except Exception as exc:  # noqa: BLE001
            self._fail("scrape", "Ocean open", exc)
        empty = [f"{county} open" for county, value in counts.items() if value.get("open") == 0]
        if empty:
            self.report["warnings"] = [f"No open listings returned: {', '.join(empty)}"]
        self.report["stages"]["scrape"] = counts

    def load(self) -> None:
        from pipeline.load_to_supabase import load_into_supabase

        loaded = 0
        for path in self.open_files + self.history_files:
            if self._record_count(path) == 0:
                continue
            try:
                self._quiet(load_into_supabase, path)
                loaded += 1
            except Exception as exc:  # noqa: BLE001
                self._fail("load", path.name, exc)
        self.report["stages"]["load"] = {"files_loaded": loaded}
        print(f"  loaded {loaded} snapshot files", flush=True)
        try:
            from pipeline.sale_results import backfill
            self.report["stages"]["sale_results"] = backfill()
        except Exception as exc:  # noqa: BLE001
            self._fail("load", "sale_results", exc)

    def link(self) -> None:
        from pipeline.create_properties import create_properties

        try:
            self._quiet(create_properties)
            self.report["stages"]["link"] = {"status": "ok"}
        except Exception as exc:  # noqa: BLE001
            self._fail("link", "create_properties", exc)

    def zillow(self) -> None:
        import pipeline.apify_scheduled_zillow as apify
        from pipeline.persist_apify_zillow import persist

        if not os.environ.get("APIFY_API_TOKEN"):
            self._fail("zillow", "token", RuntimeError("APIFY_API_TOKEN is not set"))
            return
        apify.OUTPUT = self.run_dir / "zillow"
        apify.TARGET_STATE = "NJ"
        try:
            self._quiet(apify.prepare, True)
            addresses = json.loads((apify.OUTPUT / "input.json").read_text())["addresses"]
            if not addresses:
                self.report["stages"]["zillow"] = {"submitted": 0}
                print("  no properties need a Zestimate", flush=True)
                return
            if len(addresses) > self.max_zillow_addresses:
                raise RuntimeError(
                    f"{len(addresses)} addresses exceeds the cap of {self.max_zillow_addresses}; "
                    "raise --max-zillow-addresses to approve the larger run"
                )
            apify.EXPECTED_COUNT = str(len(addresses))
            self._quiet(apify.submit)
            self._quiet(apify.watch)
            result = self._quiet(persist, apify.OUTPUT)
            run = json.loads((apify.OUTPUT / "run.json").read_text())
            stage = {"submitted": len(addresses), "matched": result["matched"],
                     "no_match": result["no_match"], "cost_usd": run.get("usageTotalUsd")}
            self.report["stages"]["zillow"] = stage
            print(f"  {stage}", flush=True)
        except Exception as exc:  # noqa: BLE001
            self._fail("zillow", "apify", exc)

    def score(self) -> None:
        import joblib

        from pipeline.train_sale_probability_model import ARTIFACT_PATH, MODEL_VERSION, _load_db_rows, score_current

        try:
            artifact = joblib.load(ARTIFACT_PATH)
            sales, histories = _load_db_rows()
            count = self._quiet(score_current, artifact["model"], sales, histories, artifact["feature_columns"],
                                artifact.get("typical"), artifact.get("metrics"))
            self.report["stages"]["score"] = {"model_version": MODEL_VERSION, "scored": count}
            print(f"  scored {count} scheduled sales with {MODEL_VERSION}", flush=True)
        except Exception as exc:  # noqa: BLE001
            self._fail("score", "sale_probability", exc)


def write_summary(report: dict[str, Any]) -> None:
    """Append a Markdown summary to the GitHub Actions job page when running there."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    before, after = report.get("before", {}), report.get("after", {})
    lines = ["## NJ Sale Refresh", "", "| Metric | Before | After |", "|---|---|---|"]
    lines += [f"| {key.replace('_', ' ')} | {before.get(key, '')} | {after.get(key, '')} |" for key in after]
    zillow = report["stages"].get("zillow")
    if zillow:
        lines += ["", f"**Zillow:** {zillow}"]
    if report["failures"]:
        lines += ["", "### Failures"] + [f"- {f['stage']} · {f['item']}: {f['error']}" for f in report["failures"]]
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stages", nargs="+", choices=STAGES, default=list(STAGES),
                        help="Run only these stages (default: all)")
    parser.add_argument("--skip-zillow", action="store_true", help="Skip the paid Apify Zillow stage")
    parser.add_argument("--max-zillow-addresses", type=int, default=400,
                        help="Refuse to submit a Zillow run larger than this (cost guard)")
    parser.add_argument("--run-dir", type=Path,
                        help="Working directory for snapshots, Apify files and the log")
    args = parser.parse_args()

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    run_dir = args.run_dir or DEFAULT_RUN_ROOT / stamp
    run_dir.mkdir(parents=True, exist_ok=True)
    refresh = Refresh(run_dir, args.max_zillow_addresses)
    stages = [stage for stage in STAGES if stage in args.stages and not (stage == "zillow" and args.skip_zillow)]
    if "load" in stages and "scrape" not in stages:
        parser.error("load needs scrape in the same run (it loads this run's snapshots)")

    print(f"NJ Sale Refresh -> {run_dir}", flush=True)
    refresh.report["before"] = snapshot_counts()
    for stage in stages:
        if stage == "report":
            continue
        print(f"[{stage}]", flush=True)
        getattr(refresh, stage)()
    refresh.report["after"] = snapshot_counts()
    refresh.report["finished_at"] = datetime.now(timezone.utc).isoformat()
    (run_dir / "report.json").write_text(json.dumps(refresh.report, indent=2, default=str) + "\n")
    write_summary(refresh.report)
    print(json.dumps({"before": refresh.report["before"], "after": refresh.report["after"],
                      "failures": len(refresh.report["failures"])}, indent=2), flush=True)
    if refresh.report["failures"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
