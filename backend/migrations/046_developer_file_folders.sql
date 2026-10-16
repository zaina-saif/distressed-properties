-- Folders for the private PDF storage (app/api/files.py). Folders are shared:
-- everyone with file access sees the same list, and developers add or remove
-- them. A file is in at most one folder; folder_id NULL means not in a folder.
BEGIN;

CREATE TABLE IF NOT EXISTS developer_file_folders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS developer_file_folders_name_idx ON developer_file_folders (lower(name));

INSERT INTO developer_file_folders (name)
VALUES ('Bronx County'), ('Kings County'), ('Manhattan'), ('Nassau County'), ('Queens County'), ('Suffolk County'), ('Westchester County')
ON CONFLICT DO NOTHING;

ALTER TABLE developer_files
    ADD COLUMN IF NOT EXISTS folder_id UUID REFERENCES developer_file_folders (id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS developer_files_folder_idx ON developer_files (folder_id);

-- The browser holds the publishable key: no access for anon/authenticated (see 034).
ALTER TABLE developer_file_folders ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON developer_file_folders FROM anon, authenticated;

COMMIT;
