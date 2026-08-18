BEGIN;

CREATE TABLE IF NOT EXISTS nj_modiv_parcel_snapshots (
    id BIGSERIAL PRIMARY KEY,
    source_year SMALLINT NOT NULL,
    municipality_code CHAR(4) NOT NULL,
    block TEXT NOT NULL,
    lot TEXT NOT NULL,
    qualifier TEXT NOT NULL DEFAULT '',
    record_id TEXT NOT NULL DEFAULT '',
    property_class TEXT,
    property_location TEXT,
    building_description TEXT,
    land_description TEXT,
    acreage NUMERIC(12, 4),
    zoning TEXT,
    deed_date DATE,
    sale_price NUMERIC(14, 2),
    sale_nonusable_code TEXT,
    building_class TEXT,
    year_built SMALLINT,
    land_assessed NUMERIC(14, 2),
    improvement_assessed NUMERIC(14, 2),
    total_assessed NUMERIC(14, 2),
    census_tract TEXT,
    census_block TEXT,
    property_use_code TEXT,
    annual_property_tax NUMERIC(14, 2),
    source_file TEXT NOT NULL,
    source_line_number INTEGER NOT NULL,
    source_hash CHAR(64) NOT NULL UNIQUE,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source_year, municipality_code, block, lot, qualifier, record_id)
);

CREATE TABLE IF NOT EXISTS nj_sr1a_sales (
    id BIGSERIAL PRIMARY KEY,
    source_year SMALLINT NOT NULL,
    county_code CHAR(2) NOT NULL,
    district_code CHAR(2) NOT NULL,
    municipality_code CHAR(4) NOT NULL,
    block TEXT NOT NULL,
    lot TEXT NOT NULL,
    property_location TEXT,
    deed_date DATE,
    recorded_date DATE,
    reported_price NUMERIC(14, 2),
    verified_price NUMERIC(14, 2),
    land_assessed NUMERIC(14, 2),
    improvement_assessed NUMERIC(14, 2),
    total_assessed NUMERIC(14, 2),
    assessment_year SMALLINT,
    property_class TEXT,
    qualification_codes TEXT,
    year_built SMALLINT,
    living_space INTEGER,
    source_file TEXT NOT NULL,
    source_line_number INTEGER NOT NULL,
    source_hash CHAR(64) NOT NULL UNIQUE,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS nj_sr1a_modiv_matches (
    sr1a_sale_id BIGINT PRIMARY KEY REFERENCES nj_sr1a_sales(id) ON DELETE CASCADE,
    modiv_snapshot_id BIGINT REFERENCES nj_modiv_parcel_snapshots(id) ON DELETE SET NULL,
    match_status TEXT NOT NULL CHECK (match_status IN ('EXACT', 'AMBIGUOUS', 'UNMATCHED')),
    candidate_count INTEGER NOT NULL DEFAULT 0,
    match_method TEXT NOT NULL,
    matched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_modiv_parcel_lookup ON nj_modiv_parcel_snapshots (source_year, municipality_code, block, lot);
CREATE INDEX IF NOT EXISTS idx_sr1a_parcel_lookup ON nj_sr1a_sales (source_year, municipality_code, block, lot);
CREATE INDEX IF NOT EXISTS idx_sr1a_model_filter ON nj_sr1a_sales (source_year, property_class, qualification_codes);
CREATE INDEX IF NOT EXISTS idx_sr1a_match_status ON nj_sr1a_modiv_matches (match_status);

COMMIT;
