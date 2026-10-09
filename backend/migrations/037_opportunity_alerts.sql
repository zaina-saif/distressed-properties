-- Opportunity alert emails: which sales each user has already been sent, so a
-- sale is emailed to a user at most once, and when each user was last emailed.
BEGIN;

ALTER TABLE investor_profiles ADD COLUMN IF NOT EXISTS last_alert_sent_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS opportunity_alert_items (
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    sheriff_sale_id UUID NOT NULL REFERENCES sheriff_sales(id) ON DELETE CASCADE,
    sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, sheriff_sale_id)
);

ALTER TABLE opportunity_alert_items ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON opportunity_alert_items FROM anon, authenticated;

COMMIT;
