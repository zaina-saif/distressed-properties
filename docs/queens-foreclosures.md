# Queens foreclosure refresh

Run from `backend/` with `../.venv`. The operational PostgreSQL schema is reused;
no migration or warehouse access is needed. The API labels this source as a
Court foreclosure auction and exposes the notice and case number.

```bash
../.venv/bin/python -m pipeline.queens_foreclosure_refresh --dry-run
../.venv/bin/python -m pipeline.queens_foreclosure_refresh --assisted --dry-run
../.venv/bin/python -m pipeline.queens_foreclosure_refresh --assisted
../.venv/bin/python -m pipeline.queens_foreclosure_refresh --assisted --county Nassau --county Suffolk --dry-run
../.venv/bin/python -m pipeline.queens_foreclosure_refresh --assisted --county all
```

`--county` (repeatable, or `all`) covers the Supreme Courts of New York
(Manhattan), Kings, Queens, Bronx, Richmond, Nassau, Suffolk, Westchester,
Orange, Onondaga and Erie (`pipeline/queens/counties.py` holds each WebCivil
court code); Queens is the default. Each county is collected and then loaded
before the next starts, so a challenge left unanswered in a later county keeps
the earlier ones. Queens loads as `nyc_queens_nyscef_foreclosure`, the others as
`ny_nyscef_foreclosure` (`<COUNTY>-NYSCEF-<index>`); a case already listed from
the Kings/Bronx Notice of Sale PDFs is counted as `already_listed`, not loaded twice.

Defaults: Queens WebCivil court **80**, today through 30 days ahead. Override
`--start YYYY-MM-DD --end YYYY-MM-DD` (maximum 90 days). Chrome must be installed.
`--profile` chooses the local browser profile; never upload it or share cookies.

The live WebCivil form captured locally on 2026-10-11 attaches hCaptcha to Find
Calendar. NYSCEF also requires guest verification. **Unattended collection is
not guaranteed:** scheduled runs stop on challenges, exit 2, and import nothing.
Use `--assisted` on the operator machine: select the foreclosure part if needed,
complete the challenge yourself, and submit Find Calendar. The collector never
solves CAPTCHAs, forges challenge tokens, changes proxies, or calls hidden
endpoints to avoid verification. After permission is established, it follows
PDF links, searches each case, visits Document List, and downloads Notice of
Sale documents through that browser's request context.

Navigation past the challenged pages needs validation against current live
court fixtures. A changed/missing selector fails closed, not as an empty county.
The existing `collect_queens_foreclosures --discover` tool remains available to
record operator-assisted HTML/PDF fixtures. PDF links must be visible court HTTPS
links; redirected downloads fail rather than following an unvalidated location.

## Daily execution (macOS operator machine)

Do not put this collector on hosted GitHub Actions: repository guidance requires
operator-local court collection. Generate and inspect the LaunchAgent:

```bash
python3 scripts/install-queens-schedule.py --output .local/queens-refresh.plist
plutil -lint .local/queens-refresh.plist
mkdir -p "$HOME/Library/LaunchAgents"
cp .local/queens-refresh.plist "$HOME/Library/LaunchAgents/ai.sheriffsalehunter.queens-refresh.plist"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/ai.sheriffsalehunter.queens-refresh.plist"
```

Runs daily at **07:15 local time** while the user's machine/session is available.
The job reads `backend/.env` only when loading; no secrets are in the plist.
To disable, use `launchctl bootout` with the same domain and plist path. An
existing loaded job must be booted out before replacing its configuration.

## Data and failure semantics

Each run gets a fresh folder under `.local/queens-refresh`; no stale snapshot is
loaded after an error. PDFs are content-addressed by SHA-256. `snapshot.json`
contains validated notices; `review.json` retains unsupported scans, ambiguity
or conflicting notices when parsing can identify them. Image-only/encrypted or
invalid PDFs stop the run for operator OCR/review. `refresh.log` retains error
tracebacks locally; the root `report.json` contains counts/status only.

Exit codes: 0 completed, 1 error, 2 access challenge, 3 review needed (unambiguous
records from that completed collection are imported). Network navigation gets
bounded retries and backoff; challenges never trigger retries or proxy fallback.
A local file lock and PostgreSQL advisory transaction lock serialize refreshes.
The database import is atomic and reuses existing property, sale, raw record and
status history storage. Sale identity is source + Queens case index; duplicate
notices do not create duplicate sales. No absent listing is retired: this is a
calendar window, not a complete sale census. Existing resolved statuses and
judgment figures are preserved, as are later recorded auction dates. Multiple
properties/dates/conflicting notices go to review. Judgment amounts are Decimal,
never opening bids or upset prices. An advertised date is not proof of sale.

## Upstream foundation and Firecrawl evaluation

Foundation reviewed: [AtheequeFurkhan/nyscef_scraper](https://github.com/AtheequeFurkhan/nyscef_scraper),
`scraper.py`, v18. Its guest-session -> court selection -> foreclosure case row
-> Document List -> document download -> pagination workflow is reimplemented
with the project's existing Playwright dependency. It targets Suffolk and
complaints, uses manual CAPTCHA/date entry and exports Excel. This adaptation
targets Queens case indices and notices and uses PostgreSQL. No upstream code is
vendored (the reviewed repository exposes no license file).

`scripts/scrape-sephora-products.mjs` was not present in this checkout, so its
implementation could not be reused. The proposed Firecrawl request is:

```json
{"url":"<permitted public document URL>","waitFor":8000,"formats":["json"],"proxy":"basic","maxAge":0}
```

[Current Firecrawl scrape documentation](https://docs.firecrawl.dev/api-reference/endpoint/scrape)
confirms the wait and JSON options, but currently lists `basic`, `enhanced`, and
`auto` for proxy; `stealth` is not a documented current value. Auto can escalate
to enhanced, so even omitting proxy is unsuitable for this collector. Neither
stealth nor enhanced is authorized to get past court challenges. Firecrawl is
**not integrated into the court transport**: it cannot satisfy manual court
verification, an 8-second delay is not access permission, and model-extracted
JSON alone is insufficient evidence for amounts or auction dates. Revisit only
for independently accessible, permitted public documents with source-text
validation. No paid Firecrawl calls are made.
