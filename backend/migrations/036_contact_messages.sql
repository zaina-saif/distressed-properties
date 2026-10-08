-- Messages sent through the website's contact form. Each is stored before it
-- is emailed, so nothing is lost if email delivery fails.
BEGIN;

CREATE TABLE IF NOT EXISTS contact_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL CHECK (char_length(name) <= 120),
    email TEXT NOT NULL CHECK (char_length(email) <= 254),
    topic TEXT NOT NULL,
    message TEXT NOT NULL CHECK (char_length(message) <= 5000),
    user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    email_status TEXT NOT NULL DEFAULT 'pending' CHECK (email_status IN ('pending', 'sent', 'failed')),
    email_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE contact_messages ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON contact_messages FROM anon, authenticated;
CREATE INDEX IF NOT EXISTS idx_contact_messages_created ON contact_messages (created_at DESC);

COMMIT;
