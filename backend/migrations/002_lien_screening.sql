BEGIN;

ALTER TABLE properties
    ADD COLUMN IF NOT EXISTS block TEXT,
    ADD COLUMN IF NOT EXISTS lot TEXT,
    ADD COLUMN IF NOT EXISTS qualifier TEXT,
    ADD COLUMN IF NOT EXISTS pams_pin TEXT,
    ADD COLUMN IF NOT EXISTS identity_confidence NUMERIC(5, 2);

CREATE TABLE IF NOT EXISTS lien_source_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    property_id UUID NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    source_name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'SUCCESS', 'PARTIAL', 'FAILED', 'MANUAL_REVIEW_REQUIRED', 'NOT_CONFIGURED'
    )),
    source_url TEXT,
    query JSONB NOT NULL DEFAULT '{}'::JSONB,
    records_found INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source_updated_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS raw_lien_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    property_id UUID NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    source_run_id UUID REFERENCES lien_source_runs(id) ON DELETE SET NULL,
    source_name TEXT NOT NULL,
    source_record_id TEXT,
    source_url TEXT,
    raw_payload JSONB NOT NULL,
    content_hash CHAR(64) NOT NULL,
    retrieved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    parser_version TEXT NOT NULL,
    UNIQUE (property_id, source_name, content_hash)
);

CREATE TABLE IF NOT EXISTS property_liens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    property_id UUID NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    sheriff_sale_id UUID REFERENCES sheriff_sales(id) ON DELETE SET NULL,
    raw_record_id UUID REFERENCES raw_lien_records(id) ON DELETE SET NULL,
    lien_type TEXT NOT NULL,
    lien_subtype TEXT,
    status TEXT NOT NULL CHECK (status IN (
        'ACTIVE', 'SATISFIED', 'DISCHARGED', 'RELEASED', 'REDEEMED',
        'EXPIRED', 'POSSIBLY_ACTIVE', 'UNKNOWN'
    )),
    creditor_name TEXT,
    debtor_name TEXT,
    original_amount NUMERIC(14, 2),
    current_amount NUMERIC(14, 2),
    recording_date DATE,
    effective_date DATE,
    release_date DATE,
    instrument_number TEXT,
    book TEXT,
    page TEXT,
    docket_number TEXT,
    case_number TEXT,
    is_foreclosing_lien BOOLEAN NOT NULL DEFAULT FALSE,
    match_confidence NUMERIC(5, 2) NOT NULL DEFAULT 0,
    match_reason TEXT NOT NULL,
    priority_classification TEXT NOT NULL DEFAULT 'UNKNOWN',
    priority_confidence NUMERIC(5, 2) NOT NULL DEFAULT 0,
    survival_classification TEXT NOT NULL DEFAULT 'UNKNOWN',
    survival_confidence NUMERIC(5, 2) NOT NULL DEFAULT 0,
    requires_manual_review BOOLEAN NOT NULL DEFAULT TRUE,
    source_name TEXT NOT NULL,
    source_url TEXT,
    source_effective_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS lien_risk_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    property_id UUID NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    sheriff_sale_id UUID REFERENCES sheriff_sales(id) ON DELETE SET NULL,
    risk_score INTEGER NOT NULL CHECK (risk_score BETWEEN 0 AND 100),
    risk_level TEXT NOT NULL,
    confidence_score INTEGER NOT NULL CHECK (confidence_score BETWEEN 0 AND 100),
    known_exposure NUMERIC(14, 2) NOT NULL DEFAULT 0,
    components JSONB NOT NULL,
    flags JSONB NOT NULL,
    source_coverage JSONB NOT NULL,
    calculation_version TEXT NOT NULL,
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_lien_source_runs_property
    ON lien_source_runs(property_id, checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_property_liens_property
    ON property_liens(property_id, status, lien_type);
CREATE INDEX IF NOT EXISTS idx_lien_risk_reports_property
    ON lien_risk_reports(property_id, calculated_at DESC);

COMMIT;
