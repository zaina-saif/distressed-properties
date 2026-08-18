BEGIN;

CREATE TABLE IF NOT EXISTS lien_category_coverage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    property_id UUID NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    source_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'RECORDS_FOUND',
        'CHECKED_NO_MATCH',
        'POSSIBLE_MATCH',
        'PARTIAL',
        'MANUAL_REVIEW_REQUIRED',
        'NOT_CHECKED',
        'SOURCE_UNAVAILABLE'
    )),
    record_count INTEGER NOT NULL DEFAULT 0,
    quantified_amount NUMERIC(14, 2),
    source_url TEXT,
    message TEXT,
    checked_at TIMESTAMPTZ,
    source_effective_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(property_id, category, source_name)
);

CREATE INDEX IF NOT EXISTS idx_lien_category_coverage_property
    ON lien_category_coverage(property_id, category);

COMMIT;
