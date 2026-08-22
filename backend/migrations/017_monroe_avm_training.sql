BEGIN;

CREATE TABLE IF NOT EXISTS pa_avm_training_sales (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    property_detail_id UUID NOT NULL UNIQUE REFERENCES pa_property_details(id) ON DELETE CASCADE,
    parcel_id UUID NOT NULL REFERENCES pa_parcels(id) ON DELETE CASCADE,
    tax_parcel_id TEXT,
    property_location TEXT,
    latitude NUMERIC(10, 7),
    longitude NUMERIC(10, 7),
    property_type TEXT,
    acreage NUMERIC(14, 4),
    assessed_value NUMERIC(14, 2),
    land_value NUMERIC(14, 2),
    improvement_value NUMERIC(14, 2),
    sale_date DATE,
    sale_price NUMERIC(14, 2),
    sale_year INTEGER,
    sale_month INTEGER,
    sale_to_assessed_ratio NUMERIC(18, 6),
    dataset_as_of DATE NOT NULL,
    training_window_start DATE NOT NULL,
    eligible_for_baseline BOOLEAN NOT NULL,
    exclusion_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
    warning_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
    preparation_version TEXT NOT NULL,
    prepared_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pa_avm_training_eligible
    ON pa_avm_training_sales (eligible_for_baseline, sale_date);

COMMIT;
