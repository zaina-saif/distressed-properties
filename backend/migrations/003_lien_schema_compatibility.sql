BEGIN;

ALTER TABLE property_liens
    ADD COLUMN IF NOT EXISTS sheriff_sale_id UUID REFERENCES sheriff_sales(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS raw_record_id UUID REFERENCES raw_lien_records(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS lien_subtype TEXT,
    ADD COLUMN IF NOT EXISTS effective_date DATE,
    ADD COLUMN IF NOT EXISTS release_date DATE,
    ADD COLUMN IF NOT EXISTS instrument_number TEXT,
    ADD COLUMN IF NOT EXISTS book TEXT,
    ADD COLUMN IF NOT EXISTS page TEXT,
    ADD COLUMN IF NOT EXISTS docket_number TEXT,
    ADD COLUMN IF NOT EXISTS case_number TEXT,
    ADD COLUMN IF NOT EXISTS is_foreclosing_lien BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS match_confidence NUMERIC(5, 2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS match_reason TEXT NOT NULL DEFAULT 'Legacy record; matching explanation unavailable.',
    ADD COLUMN IF NOT EXISTS priority_classification TEXT NOT NULL DEFAULT 'UNKNOWN',
    ADD COLUMN IF NOT EXISTS priority_confidence NUMERIC(5, 2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS survival_classification TEXT NOT NULL DEFAULT 'UNKNOWN',
    ADD COLUMN IF NOT EXISTS requires_manual_review BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS source_name TEXT,
    ADD COLUMN IF NOT EXISTS source_url TEXT,
    ADD COLUMN IF NOT EXISTS source_effective_at TIMESTAMPTZ;

UPDATE property_liens
SET source_name = COALESCE(source_name, source, 'LEGACY_IMPORT'),
    source_url = COALESCE(source_url, source_document_url),
    instrument_number = COALESCE(instrument_number, recording_number),
    survival_classification = CASE
        WHEN survival_classification <> 'UNKNOWN' THEN survival_classification
        WHEN survives_foreclosure IS TRUE THEN 'LIKELY_SURVIVES'
        WHEN survives_foreclosure IS FALSE THEN 'LIKELY_EXTINGUISHED'
        ELSE 'UNKNOWN'
    END
WHERE source_name IS NULL
   OR source_url IS NULL
   OR instrument_number IS NULL
   OR survival_classification = 'UNKNOWN';

ALTER TABLE property_liens
    ALTER COLUMN source_name SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_property_liens_source
    ON property_liens(property_id, source_name);

COMMIT;
