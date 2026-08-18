BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS properties (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    normalized_address TEXT NOT NULL,
    street_address TEXT NOT NULL,
    unit_number TEXT,
    city TEXT NOT NULL,
    municipality TEXT,
    county TEXT NOT NULL,
    state CHAR(2) NOT NULL DEFAULT 'NJ',
    zip_code VARCHAR(10),
    property_type TEXT,
    bedrooms NUMERIC(5, 2),
    bathrooms NUMERIC(5, 2),
    square_feet INTEGER,
    address_hash CHAR(64) NOT NULL UNIQUE,
    data_quality_score INTEGER NOT NULL DEFAULT 100
        CHECK (data_quality_score BETWEEN 0 AND 100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS scrape_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_name TEXT NOT NULL,
    county TEXT NOT NULL,
    source_system TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    status TEXT NOT NULL,
    records_found INTEGER NOT NULL DEFAULT 0,
    records_created INTEGER NOT NULL DEFAULT 0,
    records_updated INTEGER NOT NULL DEFAULT 0,
    records_failed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sheriff_sales (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    property_id UUID REFERENCES properties(id) ON DELETE SET NULL,
    county TEXT NOT NULL,
    sheriff_number TEXT NOT NULL,
    court_case_number TEXT,
    plaintiff TEXT,
    defendant TEXT,
    plaintiff_attorney TEXT,
    current_sale_date TIMESTAMPTZ,
    current_status TEXT NOT NULL DEFAULT 'unknown',
    judgment_amount NUMERIC(14, 2),
    upset_price NUMERIC(14, 2),
    source_url TEXT,
    source_system TEXT NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    last_scraped_at TIMESTAMPTZ NOT NULL,
    raw_source_hash CHAR(64),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (county, sheriff_number)
);

CREATE TABLE IF NOT EXISTS raw_scrape_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scrape_run_id UUID NOT NULL REFERENCES scrape_runs(id) ON DELETE CASCADE,
    county TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    source_url TEXT,
    raw_payload JSONB NOT NULL,
    content_hash CHAR(64) NOT NULL,
    parsing_status TEXT NOT NULL,
    scraped_at TIMESTAMPTZ NOT NULL,
    UNIQUE (county, source_record_id, content_hash)
);

CREATE TABLE IF NOT EXISTS sheriff_sale_status_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sheriff_sale_id UUID NOT NULL REFERENCES sheriff_sales(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    sale_date TIMESTAMPTZ,
    upset_price NUMERIC(14, 2),
    observed_at TIMESTAMPTZ NOT NULL,
    source_url TEXT,
    raw_status TEXT
);

CREATE TABLE IF NOT EXISTS property_valuations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    property_id UUID NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    estimated_value NUMERIC(14, 2) NOT NULL,
    low_value NUMERIC(14, 2),
    high_value NUMERIC(14, 2),
    confidence_score NUMERIC(5, 4),
    provider_property_id TEXT,
    provider_response JSONB,
    effective_date DATE,
    retrieved_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ,
    is_current BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS property_analyses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sheriff_sale_id UUID NOT NULL REFERENCES sheriff_sales(id) ON DELETE CASCADE,
    valuation_id UUID REFERENCES property_valuations(id) ON DELETE SET NULL,
    market_value NUMERIC(14, 2) NOT NULL,
    upset_price NUMERIC(14, 2) NOT NULL,
    gross_equity NUMERIC(14, 2) NOT NULL,
    gross_equity_percent NUMERIC(10, 6),
    surviving_lien_total NUMERIC(14, 2) NOT NULL DEFAULT 0,
    estimated_repairs NUMERIC(14, 2) NOT NULL DEFAULT 0,
    closing_costs NUMERIC(14, 2) NOT NULL DEFAULT 0,
    holding_costs NUMERIC(14, 2) NOT NULL DEFAULT 0,
    estimated_net_equity NUMERIC(14, 2) NOT NULL,
    estimated_net_equity_percent NUMERIC(10, 6),
    maximum_recommended_bid NUMERIC(14, 2) NOT NULL,
    calculation_version TEXT NOT NULL,
    assumptions JSONB NOT NULL DEFAULT '{}'::JSONB,
    calculated_at TIMESTAMPTZ NOT NULL,
    UNIQUE (sheriff_sale_id, calculation_version)
);

CREATE TABLE IF NOT EXISTS risk_assessments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sheriff_sale_id UUID NOT NULL REFERENCES sheriff_sales(id) ON DELETE CASCADE,
    risk_score INTEGER NOT NULL CHECK (risk_score BETWEEN 0 AND 100),
    risk_level TEXT NOT NULL,
    factors JSONB NOT NULL DEFAULT '{}'::JSONB,
    calculation_version TEXT NOT NULL,
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sale_predictions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sheriff_sale_id UUID NOT NULL REFERENCES sheriff_sales(id) ON DELETE CASCADE,
    probability NUMERIC(7, 6) NOT NULL CHECK (probability BETWEEN 0 AND 1),
    model_version TEXT NOT NULL,
    features JSONB NOT NULL DEFAULT '{}'::JSONB,
    predicted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_properties_county_zip
    ON properties (county, zip_code);
CREATE INDEX IF NOT EXISTS idx_sheriff_sales_status_date
    ON sheriff_sales (current_status, current_sale_date);
CREATE INDEX IF NOT EXISTS idx_sheriff_sales_property
    ON sheriff_sales (property_id);
CREATE INDEX IF NOT EXISTS idx_raw_scrape_records_lookup
    ON raw_scrape_records (county, source_record_id, scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_property_valuations_current
    ON property_valuations (property_id, is_current, retrieved_at DESC);
CREATE INDEX IF NOT EXISTS idx_property_analyses_latest
    ON property_analyses (sheriff_sale_id, calculated_at DESC);
CREATE INDEX IF NOT EXISTS idx_risk_assessments_latest
    ON risk_assessments (sheriff_sale_id, calculated_at DESC);
CREATE INDEX IF NOT EXISTS idx_sale_predictions_latest
    ON sale_predictions (sheriff_sale_id, predicted_at DESC);

COMMIT;
