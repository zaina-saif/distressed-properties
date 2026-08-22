BEGIN;

ALTER TABLE pa_property_details ADD COLUMN IF NOT EXISTS land_use_code TEXT;
ALTER TABLE pa_avm_training_sales ADD COLUMN IF NOT EXISTS land_use_code TEXT;

CREATE INDEX IF NOT EXISTS idx_pa_property_details_land_use
    ON pa_property_details (land_use_code);

COMMIT;
