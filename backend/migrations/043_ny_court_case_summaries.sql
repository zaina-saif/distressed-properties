-- NY referee foreclosure auctions: a case summary per listing, built from the case's
-- summons and complaint, Notice of Sale, WebCivil appearances and auction calendar
-- (pipeline.load_queens_pipeline). The dashboard shows it in place of a sale page
-- (app/api/court_cases.py). Party names other than the plaintiff are left out.
BEGIN;

CREATE TABLE IF NOT EXISTS ny_court_case_summaries (
    sheriff_sale_id UUID PRIMARY KEY REFERENCES sheriff_sales(id) ON DELETE CASCADE,
    county TEXT NOT NULL,
    index_number TEXT NOT NULL,
    summary JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (county, index_number)
);

-- The browser holds the publishable key: no access for anon/authenticated (see 034).
ALTER TABLE ny_court_case_summaries ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON ny_court_case_summaries FROM anon, authenticated;

COMMIT;
