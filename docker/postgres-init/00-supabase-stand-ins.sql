-- Local development only: stand-ins for what Supabase provides, so the migrations
-- in backend/migrations apply to a plain Postgres (docker compose `db`).
-- Production uses Supabase's real auth schema and roles; never run this there.
DO $$ BEGIN CREATE ROLE anon NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE authenticated NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
CREATE SCHEMA IF NOT EXISTS auth;
CREATE TABLE IF NOT EXISTS auth.users (id UUID PRIMARY KEY, email TEXT, created_at TIMESTAMPTZ DEFAULT NOW());
