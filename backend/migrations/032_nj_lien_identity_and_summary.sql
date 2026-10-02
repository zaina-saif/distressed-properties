BEGIN;

CREATE TABLE IF NOT EXISTS property_owners (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    property_id UUID NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    owner_name TEXT NOT NULL,
    normalized_owner_name TEXT NOT NULL,
    entity_type TEXT NOT NULL DEFAULT 'OTHER',
    ownership_start DATE,
    ownership_end DATE,
    is_current_owner BOOLEAN NOT NULL DEFAULT FALSE,
    mailing_address TEXT,
    source TEXT NOT NULL,
    confidence_score NUMERIC(5,2) NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(property_id, normalized_owner_name, source)
);

CREATE INDEX IF NOT EXISTS idx_property_owners_property
    ON property_owners(property_id, is_current_owner);

ALTER TABLE public_record_enrichments
    ADD COLUMN IF NOT EXISTS source_last_updated_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS data_freshness_status TEXT NOT NULL DEFAULT 'UNKNOWN';

COMMIT;
