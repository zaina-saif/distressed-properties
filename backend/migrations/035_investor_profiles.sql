-- Optional investor profiles: what each user is looking for, used to send
-- matching opportunities to users who opt in to email alerts.
-- Every field is optional; the API validates the allowed values.
BEGIN;

CREATE TABLE IF NOT EXISTS investor_profiles (
    user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    budget_range TEXT,
    states TEXT[] NOT NULL DEFAULT '{}',
    strategies TEXT[] NOT NULL DEFAULT '{}',
    property_types TEXT[] NOT NULL DEFAULT '{}',
    timeframe TEXT,
    financing TEXT,
    experience TEXT,
    min_equity TEXT,
    -- Email alerts are opt-in only; consent time is kept for compliance.
    email_alerts BOOLEAN NOT NULL DEFAULT FALSE,
    alert_frequency TEXT CHECK (alert_frequency IN ('daily', 'weekly')),
    email_alerts_consented_at TIMESTAMPTZ,
    notes TEXT CHECK (char_length(notes) <= 1000),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Same lockdown as every public table (see 034): only the API reads this.
ALTER TABLE investor_profiles ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON investor_profiles FROM anon, authenticated;

CREATE INDEX IF NOT EXISTS idx_investor_profiles_alerts ON investor_profiles (alert_frequency) WHERE email_alerts;

COMMIT;
