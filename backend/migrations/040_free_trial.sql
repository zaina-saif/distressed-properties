-- A 7-day free trial with full (Pro) coverage and no card. Each account can
-- start one trial; when it ends the account has no plan until it picks Free
-- (one county) or a paid plan. The reminder columns record which trial emails
-- were sent (pipeline.send_trial_reminders), so each goes out once.
BEGIN;

ALTER TABLE user_accounts DROP CONSTRAINT IF EXISTS user_accounts_plan_check;
ALTER TABLE user_accounts ADD CONSTRAINT user_accounts_plan_check
    CHECK (plan IN ('none', 'trial', 'free', 'starter', 'pro'));

ALTER TABLE user_accounts
    ADD COLUMN IF NOT EXISTS trial_started_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS trial_ends_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS trial_reminder_sent_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS trial_ended_sent_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS user_accounts_trial_ends_at_idx ON user_accounts (trial_ends_at) WHERE plan = 'trial';

COMMIT;
