BEGIN;

CREATE TABLE IF NOT EXISTS jurisdictions (
    id BIGSERIAL PRIMARY KEY,
    state CHAR(2) NOT NULL,
    county TEXT NOT NULL,
    municipality_code TEXT NOT NULL,
    official_name TEXT,
    jurisdiction_type TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (state, municipality_code)
);

CREATE TABLE IF NOT EXISTS jurisdiction_aliases (
    id BIGSERIAL PRIMARY KEY,
    jurisdiction_id BIGINT NOT NULL REFERENCES jurisdictions(id) ON DELETE CASCADE,
    alias TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (jurisdiction_id, normalized_alias)
);

CREATE INDEX IF NOT EXISTS idx_jurisdiction_alias_lookup
    ON jurisdiction_aliases (normalized_alias);

CREATE TABLE IF NOT EXISTS parcels (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    state CHAR(2) NOT NULL,
    county TEXT NOT NULL,
    jurisdiction_id BIGINT REFERENCES jurisdictions(id),
    municipality_code TEXT NOT NULL,
    block TEXT NOT NULL,
    lot TEXT NOT NULL,
    qualifier TEXT NOT NULL DEFAULT '',
    pams_pin TEXT NOT NULL,
    current_address TEXT,
    normalized_address TEXT,
    latitude NUMERIC(10, 7),
    longitude NUMERIC(10, 7),
    first_seen_year SMALLINT,
    last_seen_year SMALLINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (state, municipality_code, block, lot, qualifier)
);

CREATE INDEX IF NOT EXISTS idx_parcels_county_address
    ON parcels (state, county, normalized_address);
CREATE INDEX IF NOT EXISTS idx_parcels_pams_pin ON parcels (pams_pin);

CREATE TABLE IF NOT EXISTS parcel_snapshots (
    id BIGSERIAL PRIMARY KEY,
    parcel_id UUID NOT NULL REFERENCES parcels(id) ON DELETE CASCADE,
    source_year SMALLINT NOT NULL,
    property_class TEXT,
    property_location TEXT,
    building_description TEXT,
    land_description TEXT,
    acreage NUMERIC(12, 4),
    zoning TEXT,
    building_class TEXT,
    year_built SMALLINT,
    land_assessed NUMERIC(14, 2),
    improvement_assessed NUMERIC(14, 2),
    total_assessed NUMERIC(14, 2),
    annual_property_tax NUMERIC(14, 2),
    census_tract TEXT,
    census_block TEXT,
    property_use_code TEXT,
    source_file TEXT NOT NULL,
    source_line_number INTEGER NOT NULL,
    source_hash CHAR(64) NOT NULL,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (parcel_id, source_year, source_hash)
);

CREATE INDEX IF NOT EXISTS idx_parcel_snapshots_latest
    ON parcel_snapshots (parcel_id, source_year DESC);

CREATE TABLE IF NOT EXISTS parcel_identity_evidence (
    id BIGSERIAL PRIMARY KEY,
    sheriff_sale_id UUID NOT NULL REFERENCES sheriff_sales(id) ON DELETE CASCADE,
    evidence_type TEXT NOT NULL,
    raw_value TEXT,
    normalized_value TEXT,
    source_url TEXT,
    source_location TEXT,
    confidence NUMERIC(5, 2) NOT NULL DEFAULT 100
        CHECK (confidence BETWEEN 0 AND 100),
    extracted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (sheriff_sale_id, evidence_type, normalized_value, source_location)
);

CREATE INDEX IF NOT EXISTS idx_parcel_identity_evidence_sale
    ON parcel_identity_evidence (sheriff_sale_id, evidence_type);

CREATE TABLE IF NOT EXISTS parcel_match_candidates (
    id BIGSERIAL PRIMARY KEY,
    sheriff_sale_id UUID NOT NULL REFERENCES sheriff_sales(id) ON DELETE CASCADE,
    parcel_id UUID NOT NULL REFERENCES parcels(id) ON DELETE CASCADE,
    rank SMALLINT NOT NULL,
    total_score NUMERIC(6, 2) NOT NULL,
    score_components JSONB NOT NULL,
    conflicts JSONB NOT NULL DEFAULT '[]'::JSONB,
    decision TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (decision IN ('PENDING', 'ACCEPTED', 'REJECTED')),
    resolver_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed_at TIMESTAMPTZ,
    UNIQUE (sheriff_sale_id, parcel_id, resolver_version)
);

CREATE INDEX IF NOT EXISTS idx_parcel_match_candidates_review
    ON parcel_match_candidates (decision, sheriff_sale_id, rank);

CREATE TABLE IF NOT EXISTS sheriff_sale_parcels (
    id BIGSERIAL PRIMARY KEY,
    sheriff_sale_id UUID NOT NULL REFERENCES sheriff_sales(id) ON DELETE CASCADE,
    parcel_id UUID NOT NULL REFERENCES parcels(id) ON DELETE RESTRICT,
    relationship TEXT NOT NULL DEFAULT 'PRIMARY'
        CHECK (relationship IN ('PRIMARY', 'ADDITIONAL', 'CONDOMINIUM_UNIT', 'COMMON_ELEMENT')),
    match_status TEXT NOT NULL
        CHECK (match_status IN ('VERIFIED', 'MANUALLY_VERIFIED', 'POSSIBLE')),
    match_score NUMERIC(6, 2),
    match_method TEXT NOT NULL,
    evidence_summary JSONB NOT NULL DEFAULT '{}'::JSONB,
    resolver_version TEXT NOT NULL,
    reviewed_by TEXT,
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (sheriff_sale_id, parcel_id)
);

CREATE INDEX IF NOT EXISTS idx_sheriff_sale_parcels_sale
    ON sheriff_sale_parcels (sheriff_sale_id, match_status);

COMMIT;
