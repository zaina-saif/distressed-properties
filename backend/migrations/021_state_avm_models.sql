BEGIN;

ALTER TABLE public_property_snapshots
    ADD COLUMN IF NOT EXISTS rooms NUMERIC(6, 2),
    ADD COLUMN IF NOT EXISTS school_district_code TEXT,
    ADD COLUMN IF NOT EXISTS school_district_name TEXT;

CREATE TABLE IF NOT EXISTS state_avm_model_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    state CHAR(2) NOT NULL,
    model_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN
        ('TRAINING', 'PROMOTED', 'REJECTED', 'INSUFFICIENT_DATA', 'FAILED')),
    target TEXT NOT NULL DEFAULT 'sale_price',
    artifact_path TEXT,
    feature_names JSONB NOT NULL DEFAULT '[]'::JSONB,
    split_definition JSONB NOT NULL DEFAULT '{}'::JSONB,
    row_counts JSONB NOT NULL DEFAULT '{}'::JSONB,
    metrics JSONB NOT NULL DEFAULT '{}'::JSONB,
    data_as_of DATE,
    trained_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (state, model_version)
);

CREATE INDEX IF NOT EXISTS idx_state_avm_model_runs_current
    ON state_avm_model_runs (state, trained_at DESC)
    WHERE status = 'PROMOTED';

COMMIT;
