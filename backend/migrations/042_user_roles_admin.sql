-- User management (app/api/admin.py): a file_uploader role, which can only use the
-- private file storage (no sale data), and a log of every role or plan change a
-- developer makes from the admin panel.
BEGIN;

ALTER TABLE user_accounts DROP CONSTRAINT IF EXISTS user_accounts_role_check;
ALTER TABLE user_accounts ADD CONSTRAINT user_accounts_role_check
    CHECK (role IN ('user', 'developer', 'file_uploader'));

CREATE TABLE IF NOT EXISTS user_access_changes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    changed_by UUID NOT NULL,
    field TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS user_access_changes_user_idx ON user_access_changes (user_id, changed_at DESC);

-- The browser holds the publishable key: no access for anon/authenticated (see 034).
ALTER TABLE user_access_changes ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON user_access_changes FROM anon, authenticated;

COMMIT;
