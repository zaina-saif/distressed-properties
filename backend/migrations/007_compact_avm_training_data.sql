BEGIN;

DROP TABLE IF EXISTS nj_sr1a_modiv_matches;
DROP TABLE IF EXISTS nj_sr1a_sales;
DROP TABLE IF EXISTS nj_modiv_parcel_snapshots;

CREATE TABLE IF NOT EXISTS nj_avm_training_sales (
    id BIGSERIAL PRIMARY KEY,
    sale_year SMALLINT NOT NULL,
    snapshot_year SMALLINT NOT NULL,
    municipality_code CHAR(4) NOT NULL,
    block TEXT NOT NULL,
    lot TEXT NOT NULL,
    qualifier TEXT NOT NULL DEFAULT '',
    property_location TEXT,
    deed_date DATE,
    recorded_date DATE,
    sale_price NUMERIC(14, 2) NOT NULL,
    reported_price NUMERIC(14, 2),
    verified_price NUMERIC(14, 2),
    property_class TEXT NOT NULL,
    qualification_codes TEXT NOT NULL DEFAULT '',
    building_description TEXT,
    land_description TEXT,
    acreage NUMERIC(12, 4),
    zoning TEXT,
    building_class TEXT,
    year_built SMALLINT,
    living_space INTEGER,
    land_assessed NUMERIC(14, 2),
    improvement_assessed NUMERIC(14, 2),
    total_assessed NUMERIC(14, 2),
    annual_property_tax NUMERIC(14, 2),
    census_tract TEXT,
    census_block TEXT,
    property_use_code TEXT,
    match_method TEXT NOT NULL,
    source_hash CHAR(64) NOT NULL UNIQUE,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_avm_training_location
    ON nj_avm_training_sales (municipality_code, deed_date);
CREATE INDEX IF NOT EXISTS idx_avm_training_parcel
    ON nj_avm_training_sales (municipality_code, block, lot);
CREATE INDEX IF NOT EXISTS idx_avm_training_year
    ON nj_avm_training_sales (sale_year, snapshot_year);

COMMIT;
