-- Catch-up: tables and columns production has that no earlier migration created
-- (they were added directly to the Supabase database). Every statement is skipped
-- when the object exists, so this is a no-op on production and makes a fresh
-- database (docker compose `db`) match it.

BEGIN;

-- properties
ALTER TABLE public.properties ADD COLUMN IF NOT EXISTS latitude numeric(10,7);
ALTER TABLE public.properties ADD COLUMN IF NOT EXISTS longitude numeric(10,7);
ALTER TABLE public.properties ADD COLUMN IF NOT EXISTS parcel_number text;
ALTER TABLE public.properties ADD COLUMN IF NOT EXISTS lot_size_sqft integer;
-- property_liens
ALTER TABLE public.property_liens ADD COLUMN IF NOT EXISTS priority_position integer;
ALTER TABLE public.property_liens ADD COLUMN IF NOT EXISTS source_data jsonb;
ALTER TABLE public.property_liens ADD COLUMN IF NOT EXISTS verified_at timestamp with time zone;
-- raw_scrape_records
ALTER TABLE public.raw_scrape_records ADD COLUMN IF NOT EXISTS parsing_error text;
-- risk_assessments
ALTER TABLE public.risk_assessments ADD COLUMN IF NOT EXISTS lien_risk_score smallint;
ALTER TABLE public.risk_assessments ADD COLUMN IF NOT EXISTS title_risk_score smallint;
ALTER TABLE public.risk_assessments ADD COLUMN IF NOT EXISTS data_quality_risk_score smallint;
ALTER TABLE public.risk_assessments ADD COLUMN IF NOT EXISTS sale_process_risk_score smallint;
ALTER TABLE public.risk_assessments ADD COLUMN IF NOT EXISTS missing_information jsonb;
ALTER TABLE public.risk_assessments ADD COLUMN IF NOT EXISTS scoring_version text;
-- sale_predictions
ALTER TABLE public.sale_predictions ADD COLUMN IF NOT EXISTS prediction_target text;
ALTER TABLE public.sale_predictions ADD COLUMN IF NOT EXISTS predicted_class boolean;
ALTER TABLE public.sale_predictions ADD COLUMN IF NOT EXISTS model_name text;
ALTER TABLE public.sale_predictions ADD COLUMN IF NOT EXISTS feature_values jsonb;
ALTER TABLE public.sale_predictions ADD COLUMN IF NOT EXISTS feature_explanations jsonb;
-- scrape_runs
ALTER TABLE public.scrape_runs ADD COLUMN IF NOT EXISTS error_message text;
ALTER TABLE public.scrape_runs ADD COLUMN IF NOT EXISTS execution_metadata jsonb;
ALTER TABLE public.scrape_runs ADD COLUMN IF NOT EXISTS created_at timestamp with time zone DEFAULT now() NOT NULL;
-- sheriff_sales
ALTER TABLE public.sheriff_sales ADD COLUMN IF NOT EXISTS original_sale_date timestamp with time zone;
ALTER TABLE public.sheriff_sales ADD COLUMN IF NOT EXISTS deed_type text;
ALTER TABLE public.sheriff_sales ADD COLUMN IF NOT EXISTS sale_location text;
ALTER TABLE public.sheriff_sales ADD COLUMN IF NOT EXISTS docket_number text;
ALTER TABLE public.sheriff_sales ADD COLUMN IF NOT EXISTS estimated_upset_price numeric(14,2);
ALTER TABLE public.sheriff_sales ADD COLUMN IF NOT EXISTS alternate_upset_price numeric(14,2);
ALTER TABLE public.sheriff_sales ADD COLUMN IF NOT EXISTS daily_interest numeric(14,2);
ALTER TABLE public.sheriff_sales ADD COLUMN IF NOT EXISTS attorney_fees_costs numeric(14,2);
ALTER TABLE public.sheriff_sales ADD COLUMN IF NOT EXISTS deposit_percent numeric(5,2);
ALTER TABLE public.sheriff_sales ADD COLUMN IF NOT EXISTS balance_due_days integer;
ALTER TABLE public.sheriff_sales ADD COLUMN IF NOT EXISTS owner_occupied boolean;
ALTER TABLE public.sheriff_sales ADD COLUMN IF NOT EXISTS description_text text;
ALTER TABLE public.sheriff_sales ADD COLUMN IF NOT EXISTS description_source_url text;
ALTER TABLE public.sheriff_sales ADD COLUMN IF NOT EXISTS description_parsed_at timestamp with time zone;
ALTER TABLE public.sheriff_sales ADD COLUMN IF NOT EXISTS parser_version text;
ALTER TABLE public.sheriff_sales ADD COLUMN IF NOT EXISTS upset_price_conflict boolean DEFAULT false;

CREATE TABLE IF NOT EXISTS public.canonical_sale_events (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    sheriff_sale_id uuid NOT NULL,
    property_id uuid,
    state character(2) NOT NULL,
    county text NOT NULL,
    normalized_status text NOT NULL,
    raw_status text NOT NULL,
    event_effective_at timestamp with time zone,
    event_key character(64) NOT NULL,
    first_observed_at timestamp with time zone NOT NULL,
    last_observed_at timestamp with time zone NOT NULL,
    observation_count integer NOT NULL,
    source_url text,
    source_record_hash text,
    verification_state text DEFAULT 'observed'::text NOT NULL,
    evidence jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT canonical_sale_events_observation_count_check CHECK ((observation_count > 0)),
    CONSTRAINT canonical_sale_events_verification_state_check CHECK ((verification_state = ANY (ARRAY['verified'::text, 'observed'::text, 'provisional'::text, 'unknown'::text])))
);

CREATE TABLE IF NOT EXISTS public.sale_attempt_outcomes (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    sheriff_sale_id uuid NOT NULL,
    property_id uuid,
    outcome_label text NOT NULL,
    outcome_subtype text,
    verification_state text NOT NULL,
    outcome_effective_at timestamp with time zone,
    canonical_event_id uuid,
    source_url text,
    source_record_hash text,
    evidence jsonb DEFAULT '{}'::jsonb NOT NULL,
    labeled_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT sale_attempt_outcomes_outcome_label_check CHECK ((outcome_label = ANY (ARRAY['confirmed_sold'::text, 'observed_competing_outcome'::text, 'unresolved'::text]))),
    CONSTRAINT sale_attempt_outcomes_verification_state_check CHECK ((verification_state = ANY (ARRAY['verified'::text, 'observed'::text, 'provisional'::text, 'unknown'::text])))
);

CREATE TABLE IF NOT EXISTS public.sale_feature_snapshots (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    sheriff_sale_id uuid NOT NULL,
    property_id uuid,
    as_of_at timestamp with time zone NOT NULL,
    source_event_id uuid,
    feature_version text NOT NULL,
    feature_values jsonb NOT NULL,
    provenance jsonb DEFAULT '{}'::jsonb NOT NULL,
    data_quality jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE IF NOT EXISTS public.saved_searches (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    name text NOT NULL,
    filters jsonb NOT NULL,
    sort_configuration jsonb,
    notifications_enabled boolean DEFAULT false,
    notification_frequency text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.scheduled_sale_snapshots (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    sheriff_sale_id uuid NOT NULL,
    property_id uuid,
    observed_at timestamp with time zone NOT NULL,
    state character(2) NOT NULL,
    county text NOT NULL,
    source_system text NOT NULL,
    observed_status text NOT NULL,
    scheduled_for timestamp with time zone,
    source_url text,
    source_record_hash text,
    snapshot_reason text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT scheduled_sale_snapshots_snapshot_reason_check CHECK ((snapshot_reason = ANY (ARRAY['initial_baseline'::text, 'collection_run'::text])))
);

CREATE TABLE IF NOT EXISTS public.sheriff_sale_charges (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    sheriff_sale_id uuid NOT NULL,
    charge_type text NOT NULL,
    amount numeric(14,2),
    description text,
    effective_date date,
    source_text text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE IF NOT EXISTS public.user_profiles (
    id uuid NOT NULL,
    display_name text,
    subscription_tier text DEFAULT 'free'::text,
    created_at timestamp with time zone DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.watchlist_properties (
    watchlist_id uuid NOT NULL,
    sheriff_sale_id uuid NOT NULL,
    notes text,
    created_at timestamp with time zone DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.watchlists (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    name text NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);

DO $$ BEGIN
    ALTER TABLE ONLY public.canonical_sale_events
        ADD CONSTRAINT canonical_sale_events_pkey PRIMARY KEY (id);
EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE ONLY public.canonical_sale_events
        ADD CONSTRAINT canonical_sale_events_sheriff_sale_id_event_key_key UNIQUE (sheriff_sale_id, event_key);
EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE ONLY public.sale_attempt_outcomes
        ADD CONSTRAINT sale_attempt_outcomes_pkey PRIMARY KEY (id);
EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE ONLY public.sale_attempt_outcomes
        ADD CONSTRAINT sale_attempt_outcomes_sheriff_sale_id_key UNIQUE (sheriff_sale_id);
EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE ONLY public.sale_feature_snapshots
        ADD CONSTRAINT sale_feature_snapshots_pkey PRIMARY KEY (id);
EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE ONLY public.sale_feature_snapshots
        ADD CONSTRAINT sale_feature_snapshots_sheriff_sale_id_as_of_at_feature_ver_key UNIQUE (sheriff_sale_id, as_of_at, feature_version);
EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE ONLY public.saved_searches
        ADD CONSTRAINT saved_searches_pkey PRIMARY KEY (id);
EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE ONLY public.scheduled_sale_snapshots
        ADD CONSTRAINT scheduled_sale_snapshots_pkey PRIMARY KEY (id);
EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE ONLY public.scheduled_sale_snapshots
        ADD CONSTRAINT scheduled_sale_snapshots_sheriff_sale_id_observed_at_key UNIQUE (sheriff_sale_id, observed_at);
EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE ONLY public.sheriff_sale_charges
        ADD CONSTRAINT sheriff_sale_charges_pkey PRIMARY KEY (id);
EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE ONLY public.user_profiles
        ADD CONSTRAINT user_profiles_pkey PRIMARY KEY (id);
EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE ONLY public.watchlist_properties
        ADD CONSTRAINT watchlist_properties_pkey PRIMARY KEY (watchlist_id, sheriff_sale_id);
EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE ONLY public.watchlists
        ADD CONSTRAINT watchlists_pkey PRIMARY KEY (id);
EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_canonical_sale_events_attempt_date ON public.canonical_sale_events USING btree (sheriff_sale_id, event_effective_at, first_observed_at);

CREATE INDEX IF NOT EXISTS idx_canonical_sale_events_property ON public.canonical_sale_events USING btree (property_id) WHERE (property_id IS NOT NULL);

CREATE INDEX IF NOT EXISTS idx_sale_attempt_outcomes_label ON public.sale_attempt_outcomes USING btree (outcome_label, verification_state);

CREATE INDEX IF NOT EXISTS idx_sale_attempt_outcomes_property ON public.sale_attempt_outcomes USING btree (property_id) WHERE (property_id IS NOT NULL);

CREATE INDEX IF NOT EXISTS idx_sale_feature_snapshots_attempt_as_of ON public.sale_feature_snapshots USING btree (sheriff_sale_id, as_of_at DESC);

CREATE INDEX IF NOT EXISTS idx_scheduled_sale_snapshots_attempt_time ON public.scheduled_sale_snapshots USING btree (sheriff_sale_id, observed_at);

CREATE INDEX IF NOT EXISTS idx_scheduled_sale_snapshots_status_time ON public.scheduled_sale_snapshots USING btree (observed_status, observed_at);

CREATE INDEX IF NOT EXISTS idx_sheriff_sale_charges_sale ON public.sheriff_sale_charges USING btree (sheriff_sale_id);

DO $$ BEGIN
    ALTER TABLE ONLY public.canonical_sale_events
        ADD CONSTRAINT canonical_sale_events_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE ONLY public.canonical_sale_events
        ADD CONSTRAINT canonical_sale_events_sheriff_sale_id_fkey FOREIGN KEY (sheriff_sale_id) REFERENCES public.sheriff_sales(id) ON DELETE CASCADE;
EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE ONLY public.sale_attempt_outcomes
        ADD CONSTRAINT sale_attempt_outcomes_canonical_event_id_fkey FOREIGN KEY (canonical_event_id) REFERENCES public.canonical_sale_events(id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE ONLY public.sale_attempt_outcomes
        ADD CONSTRAINT sale_attempt_outcomes_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE ONLY public.sale_attempt_outcomes
        ADD CONSTRAINT sale_attempt_outcomes_sheriff_sale_id_fkey FOREIGN KEY (sheriff_sale_id) REFERENCES public.sheriff_sales(id) ON DELETE CASCADE;
EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE ONLY public.sale_feature_snapshots
        ADD CONSTRAINT sale_feature_snapshots_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE ONLY public.sale_feature_snapshots
        ADD CONSTRAINT sale_feature_snapshots_sheriff_sale_id_fkey FOREIGN KEY (sheriff_sale_id) REFERENCES public.sheriff_sales(id) ON DELETE CASCADE;
EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE ONLY public.sale_feature_snapshots
        ADD CONSTRAINT sale_feature_snapshots_source_event_id_fkey FOREIGN KEY (source_event_id) REFERENCES public.canonical_sale_events(id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE ONLY public.saved_searches
        ADD CONSTRAINT saved_searches_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.user_profiles(id);
EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE ONLY public.scheduled_sale_snapshots
        ADD CONSTRAINT scheduled_sale_snapshots_property_id_fkey FOREIGN KEY (property_id) REFERENCES public.properties(id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE ONLY public.scheduled_sale_snapshots
        ADD CONSTRAINT scheduled_sale_snapshots_sheriff_sale_id_fkey FOREIGN KEY (sheriff_sale_id) REFERENCES public.sheriff_sales(id) ON DELETE CASCADE;
EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE ONLY public.sheriff_sale_charges
        ADD CONSTRAINT sheriff_sale_charges_sheriff_sale_id_fkey FOREIGN KEY (sheriff_sale_id) REFERENCES public.sheriff_sales(id) ON DELETE CASCADE;
EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE ONLY public.watchlist_properties
        ADD CONSTRAINT watchlist_properties_sheriff_sale_id_fkey FOREIGN KEY (sheriff_sale_id) REFERENCES public.sheriff_sales(id) ON DELETE CASCADE;
EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE ONLY public.watchlist_properties
        ADD CONSTRAINT watchlist_properties_watchlist_id_fkey FOREIGN KEY (watchlist_id) REFERENCES public.watchlists(id) ON DELETE CASCADE;
EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE ONLY public.watchlists
        ADD CONSTRAINT watchlists_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.user_profiles(id);
EXCEPTION WHEN duplicate_object OR duplicate_table OR invalid_table_definition THEN NULL;
END $$;

ALTER TABLE public.canonical_sale_events ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.sale_attempt_outcomes ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.sale_feature_snapshots ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.saved_searches ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.scheduled_sale_snapshots ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.sheriff_sale_charges ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.user_profiles ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.watchlist_properties ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.watchlists ENABLE ROW LEVEL SECURITY;

COMMIT;
