BEGIN;

ALTER TABLE pa_parcels ADD COLUMN IF NOT EXISTS tax_parcel_id TEXT;
ALTER TABLE pa_parcels ADD COLUMN IF NOT EXISTS normalized_tax_parcel_id TEXT;

CREATE INDEX IF NOT EXISTS idx_pa_parcels_tax_parcel_id
    ON pa_parcels (state, county, normalized_tax_parcel_id);

CREATE TABLE IF NOT EXISTS pa_property_details (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parcel_id UUID NOT NULL UNIQUE REFERENCES pa_parcels(id) ON DELETE CASCADE,
    map_number TEXT NOT NULL,
    tax_parcel_id TEXT,
    normalized_tax_parcel_id TEXT,
    owner_name TEXT,
    assessed_value NUMERIC(14, 2),
    land_value NUMERIC(14, 2),
    improvement_value NUMERIC(14, 2),
    preferential_value NUMERIC(14, 2),
    property_type TEXT,
    acreage NUMERIC(14, 4),
    property_location TEXT,
    last_sale_date DATE,
    last_sale_price NUMERIC(14, 2),
    assessment_year INTEGER,
    enrichment_source TEXT NOT NULL,
    source_object_id BIGINT,
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pa_property_details_tax_parcel
    ON pa_property_details (normalized_tax_parcel_id);

COMMIT;
