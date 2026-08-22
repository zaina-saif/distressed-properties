BEGIN;

CREATE TABLE IF NOT EXISTS pa_parcels (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    state CHAR(2) NOT NULL DEFAULT 'PA',
    county TEXT NOT NULL,
    map_number TEXT NOT NULL,
    normalized_map_number TEXT NOT NULL,
    source_object_id BIGINT NOT NULL,
    geometry JSONB NOT NULL,
    latitude NUMERIC(10, 7),
    longitude NUMERIC(10, 7),
    source TEXT NOT NULL,
    source_layer TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (state, county, normalized_map_number),
    UNIQUE (source, source_object_id)
);

CREATE INDEX IF NOT EXISTS idx_pa_parcels_map_number
    ON pa_parcels (state, county, normalized_map_number);
CREATE INDEX IF NOT EXISTS idx_pa_parcels_coordinates
    ON pa_parcels (latitude, longitude);

CREATE TABLE IF NOT EXISTS pa_sheriff_sale_parcel_matches (
    id BIGSERIAL PRIMARY KEY,
    sheriff_sale_id UUID NOT NULL REFERENCES sheriff_sales(id) ON DELETE CASCADE,
    parcel_id UUID NOT NULL REFERENCES pa_parcels(id) ON DELETE RESTRICT,
    raw_map_number TEXT NOT NULL,
    normalized_map_number TEXT NOT NULL,
    match_method TEXT NOT NULL,
    match_status TEXT NOT NULL CHECK (match_status IN ('EXACT', 'NORMALIZED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (sheriff_sale_id, parcel_id)
);

CREATE INDEX IF NOT EXISTS idx_pa_sale_parcel_match_sale
    ON pa_sheriff_sale_parcel_matches (sheriff_sale_id);

COMMIT;
