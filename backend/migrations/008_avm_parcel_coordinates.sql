BEGIN;

ALTER TABLE nj_avm_training_sales
    ADD COLUMN IF NOT EXISTS latitude DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS longitude DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS coordinate_source TEXT;

CREATE INDEX IF NOT EXISTS idx_avm_training_coordinates
    ON nj_avm_training_sales (latitude, longitude)
    WHERE latitude IS NOT NULL AND longitude IS NOT NULL;

COMMIT;
