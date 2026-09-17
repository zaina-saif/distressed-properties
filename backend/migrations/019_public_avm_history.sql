BEGIN;

CREATE TABLE IF NOT EXISTS public_data_sources (
    source_id TEXT PRIMARY KEY,
    state CHAR(2) NOT NULL,
    county TEXT,
    source_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    access_method TEXT NOT NULL,
    coverage_notes TEXT,
    last_checked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public_property_snapshots (
    id BIGSERIAL PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES public_data_sources(source_id),
    state CHAR(2) NOT NULL,
    county TEXT NOT NULL,
    source_parcel_id TEXT NOT NULL,
    snapshot_year SMALLINT NOT NULL,
    street_address TEXT,
    city TEXT,
    zip_code TEXT,
    longitude DOUBLE PRECISION,
    latitude DOUBLE PRECISION,
    property_type TEXT,
    land_use_code TEXT,
    year_built SMALLINT,
    living_area INTEGER,
    land_area NUMERIC(16, 4),
    land_area_unit TEXT,
    bedrooms NUMERIC(6, 2),
    bathrooms NUMERIC(6, 2),
    land_value NUMERIC(16, 2),
    improvement_value NUMERIC(16, 2),
    total_assessed_value NUMERIC(16, 2),
    source_updated_at TIMESTAMPTZ,
    source_hash CHAR(64) NOT NULL,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source_id, source_parcel_id, snapshot_year)
);

CREATE TABLE IF NOT EXISTS public_property_sales (
    id BIGSERIAL PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES public_data_sources(source_id),
    state CHAR(2) NOT NULL,
    county TEXT NOT NULL,
    source_parcel_id TEXT NOT NULL,
    transaction_id TEXT NOT NULL,
    sale_date DATE NOT NULL,
    recording_date DATE,
    sale_price NUMERIC(16, 2) NOT NULL,
    conveyance_code TEXT,
    arms_length BOOLEAN,
    source_hash CHAR(64) NOT NULL,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source_id, source_parcel_id, transaction_id)
);

CREATE INDEX IF NOT EXISTS idx_public_property_snapshots_location
    ON public_property_snapshots (state, county, snapshot_year);
CREATE INDEX IF NOT EXISTS idx_public_property_snapshots_parcel
    ON public_property_snapshots (state, county, source_parcel_id);
CREATE INDEX IF NOT EXISTS idx_public_property_sales_date
    ON public_property_sales (state, county, sale_date);
CREATE INDEX IF NOT EXISTS idx_public_property_sales_parcel
    ON public_property_sales (state, county, source_parcel_id);
CREATE INDEX IF NOT EXISTS idx_public_property_sales_training
    ON public_property_sales (state, county, sale_date, sale_price)
    WHERE sale_price > 0;

COMMIT;
