-- Private PDF storage for the developer account (app/api/files.py): files are
-- uploaded one by one or as a zip, then downloaded or deleted. Each row holds
-- the whole file; the same PDF (by SHA-256) is stored once per user.
BEGIN;

CREATE TABLE IF NOT EXISTS developer_files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    filename TEXT NOT NULL,
    source_zip TEXT,
    content_type TEXT NOT NULL DEFAULT 'application/pdf',
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    content BYTEA NOT NULL,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, sha256)
);

CREATE INDEX IF NOT EXISTS developer_files_user_uploaded_idx ON developer_files (user_id, uploaded_at DESC);

-- The browser holds the publishable key: no access for anon/authenticated (see 034).
ALTER TABLE developer_files ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON developer_files FROM anon, authenticated;

COMMIT;
