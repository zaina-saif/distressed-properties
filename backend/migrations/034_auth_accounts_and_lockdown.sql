-- Accounts, plans and billing state for Supabase Auth users, and a lockdown of
-- Supabase's public Data API.
--
-- The frontend now ships the project's publishable (anon) key for sign-in.
-- That key can query every table in "public" through Supabase's REST API
-- unless row-level security is on, which would bypass the API's plan checks.
-- All data goes through the FastAPI backend, which connects as "postgres"
-- (BYPASSRLS), so the public roles get no table access at all.
BEGIN;

CREATE TABLE IF NOT EXISTS user_accounts (
    user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'developer')),
    plan TEXT NOT NULL DEFAULT 'none' CHECK (plan IN ('none', 'free', 'starter', 'pro')),
    plan_status TEXT NOT NULL DEFAULT 'inactive'
        CHECK (plan_status IN ('inactive', 'active', 'trialing', 'past_due', 'canceled')),
    billing_interval TEXT CHECK (billing_interval IN ('month', 'year')),
    -- Free covers one county, Starter one state; Pro and developers cover everything.
    coverage_state TEXT,
    coverage_county TEXT,
    coverage_changed_at TIMESTAMPTZ,
    stripe_customer_id TEXT UNIQUE,
    stripe_subscription_id TEXT UNIQUE,
    current_period_end TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Stripe retries webhooks; each event is applied once.
CREATE TABLE IF NOT EXISTS stripe_events (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
DECLARE
    table_name TEXT;
BEGIN
    FOR table_name IN
        SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
    LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', table_name);
    END LOOP;
END $$;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM anon, authenticated;
-- Tables created later by "postgres" stay closed too.
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE ALL ON TABLES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE ALL ON SEQUENCES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE EXECUTE ON FUNCTIONS FROM anon, authenticated;

COMMIT;
