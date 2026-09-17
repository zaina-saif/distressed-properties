BEGIN;

CREATE TABLE IF NOT EXISTS public_parcel_addresses (
    source_id TEXT NOT NULL REFERENCES public_data_sources(source_id),
    state CHAR(2) NOT NULL,
    county TEXT NOT NULL,
    source_parcel_id TEXT NOT NULL,
    as_of_year SMALLINT NOT NULL,
    street_address TEXT NOT NULL,
    city TEXT,
    zip_code TEXT,
    house_number_unavailable BOOLEAN NOT NULL DEFAULT FALSE,
    source_hash CHAR(64) NOT NULL,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (source_id, source_parcel_id, as_of_year)
);

CREATE INDEX IF NOT EXISTS idx_public_parcel_addresses_lookup
    ON public_parcel_addresses (state, county, source_parcel_id, as_of_year DESC);

COMMIT;
