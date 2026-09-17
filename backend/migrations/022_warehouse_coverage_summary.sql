BEGIN;

CREATE TABLE IF NOT EXISTS public_property_coverage_yearly (
    state CHAR(2) NOT NULL,
    year SMALLINT NOT NULL,
    sale_count BIGINT NOT NULL DEFAULT 0,
    sale_counties INTEGER NOT NULL DEFAULT 0,
    snapshot_count BIGINT NOT NULL DEFAULT 0,
    snapshot_counties INTEGER NOT NULL DEFAULT 0,
    snapshot_county_names TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    first_sale DATE,
    last_sale DATE,
    refreshed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (state, year)
);

CREATE TABLE IF NOT EXISTS public_property_coverage_state (
    state CHAR(2) PRIMARY KEY,
    future_dated_sales BIGINT NOT NULL DEFAULT 0,
    refreshed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMIT;
