BEGIN;

-- Preserve the existing raw_lien_records table while adding the audit fields
-- required for a public-record source adapter.
ALTER TABLE raw_lien_records
    ADD COLUMN IF NOT EXISTS source_type TEXT,
    ADD COLUMN IF NOT EXISTS search_type TEXT,
    ADD COLUMN IF NOT EXISTS search_query JSONB NOT NULL DEFAULT '{}'::JSONB,
    ADD COLUMN IF NOT EXISTS raw_html TEXT,
    ADD COLUMN IF NOT EXISTS source_last_updated TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS ingestion_status TEXT NOT NULL DEFAULT 'INGESTED';

CREATE TABLE IF NOT EXISTS raw_public_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    property_id UUID REFERENCES properties(id) ON DELETE CASCADE,
    source_name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_url TEXT,
    source_record_id TEXT,
    search_type TEXT,
    search_query JSONB NOT NULL DEFAULT '{}'::JSONB,
    raw_data JSONB NOT NULL,
    raw_html TEXT,
    retrieved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source_last_updated TIMESTAMPTZ,
    ingestion_status TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    UNIQUE(property_id, source_name, content_hash)
);

ALTER TABLE property_liens
    ADD COLUMN IF NOT EXISTS source_record_id TEXT,
    ADD COLUMN IF NOT EXISTS county TEXT,
    ADD COLUMN IF NOT EXISTS municipality TEXT,
    ADD COLUMN IF NOT EXISTS block TEXT,
    ADD COLUMN IF NOT EXISTS lot TEXT,
    ADD COLUMN IF NOT EXISTS qualifier TEXT,
    ADD COLUMN IF NOT EXISTS pams_pin TEXT,
    ADD COLUMN IF NOT EXISTS property_address TEXT,
    ADD COLUMN IF NOT EXISTS matching_method TEXT,
    ADD COLUMN IF NOT EXISTS priority_category TEXT,
    ADD COLUMN IF NOT EXISTS priority_score NUMERIC(5, 2),
    ADD COLUMN IF NOT EXISTS survival_probability NUMERIC(5, 2);

CREATE TABLE IF NOT EXISTS lien_relationships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_lien_id UUID NOT NULL REFERENCES property_liens(id) ON DELETE CASCADE,
    child_lien_id UUID NOT NULL REFERENCES property_liens(id) ON DELETE CASCADE,
    relationship_type TEXT NOT NULL,
    confidence NUMERIC(5, 2) NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(parent_lien_id, child_lien_id, relationship_type)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_property_liens_source_record
    ON property_liens(property_id, source_name, source_record_id)
    WHERE source_record_id IS NOT NULL;

COMMIT;
