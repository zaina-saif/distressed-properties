BEGIN;

ALTER TABLE public_property_snapshots
    ADD COLUMN IF NOT EXISTS market_value NUMERIC(16, 2);

CREATE TABLE IF NOT EXISTS public_import_files (
    source_id TEXT NOT NULL REFERENCES public_data_sources(source_id),
    file_name TEXT NOT NULL,
    file_url TEXT NOT NULL,
    file_size BIGINT,
    sha256 CHAR(64),
    row_count BIGINT NOT NULL DEFAULT 0,
    status TEXT NOT NULL CHECK (status IN ('completed', 'failed')),
    completed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (source_id, file_name)
);

CREATE INDEX IF NOT EXISTS idx_public_import_files_status
    ON public_import_files (source_id, status, completed_at);

COMMIT;
