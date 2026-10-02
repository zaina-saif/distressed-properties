BEGIN;

CREATE TABLE IF NOT EXISTS public_record_enrichments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    property_id UUID NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    primary_lender TEXT,
    municipal_violations_count INTEGER,
    estimated_municipal_debt_usd NUMERIC(14,2),
    outstanding_taxes_usd NUMERIC(14,2),
    tax_delinquency_status TEXT,
    source_statuses JSONB NOT NULL DEFAULT '{}'::JSONB,
    source_urls JSONB NOT NULL DEFAULT '[]'::JSONB,
    raw_data JSONB NOT NULL DEFAULT '{}'::JSONB,
    error_message TEXT,
    retrieved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(property_id)
);

CREATE INDEX IF NOT EXISTS idx_public_record_enrichments_status
    ON public_record_enrichments(status);

COMMIT;
