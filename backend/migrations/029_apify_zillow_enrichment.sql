BEGIN;

CREATE TABLE IF NOT EXISTS apify_zillow_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    apify_run_id TEXT NOT NULL UNIQUE,
    actor TEXT NOT NULL,
    dataset_id TEXT,
    submitted_at TIMESTAMPTZ,
    retrieved_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL,
    submitted_address_count INTEGER NOT NULL DEFAULT 0,
    returned_item_count INTEGER NOT NULL DEFAULT 0,
    metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS apify_zillow_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES apify_zillow_runs(id) ON DELETE CASCADE,
    property_id UUID REFERENCES properties(id) ON DELETE SET NULL,
    submitted_address TEXT NOT NULL,
    match_status TEXT NOT NULL CHECK (match_status IN ('matched', 'no_match', 'invalid')),
    zillow_id TEXT,
    zestimate NUMERIC(14, 2),
    raw_payload JSONB NOT NULL DEFAULT '{}'::JSONB,
    retrieved_at TIMESTAMPTZ NOT NULL,
    is_current BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, submitted_address)
);

CREATE INDEX IF NOT EXISTS idx_apify_zillow_results_current
    ON apify_zillow_results (property_id, is_current, retrieved_at DESC);
CREATE INDEX IF NOT EXISTS idx_apify_zillow_results_run
    ON apify_zillow_results (run_id, submitted_address);

COMMIT;
