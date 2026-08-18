BEGIN;

CREATE TABLE IF NOT EXISTS property_avm_features (
    property_id UUID PRIMARY KEY REFERENCES properties(id) ON DELETE CASCADE,
    snapshot_year SMALLINT NOT NULL,
    municipality_code CHAR(4) NOT NULL,
    block TEXT NOT NULL,
    lot TEXT NOT NULL,
    qualifier TEXT NOT NULL DEFAULT '',
    property_class TEXT,
    property_location TEXT,
    acreage NUMERIC(12,4),
    zoning TEXT,
    building_class TEXT,
    year_built SMALLINT,
    land_assessed NUMERIC(14,2),
    improvement_assessed NUMERIC(14,2),
    total_assessed NUMERIC(14,2),
    annual_property_tax NUMERIC(14,2),
    census_tract TEXT,
    property_use_code TEXT,
    match_method TEXT NOT NULL,
    match_confidence NUMERIC(5,2) NOT NULL,
    source_hash CHAR(64) NOT NULL,
    matched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMIT;
