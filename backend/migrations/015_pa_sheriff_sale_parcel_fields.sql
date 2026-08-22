BEGIN;

ALTER TABLE sheriff_sales ADD COLUMN IF NOT EXISTS property_number TEXT;
ALTER TABLE sheriff_sales ADD COLUMN IF NOT EXISTS map_number TEXT;
ALTER TABLE sheriff_sales ADD COLUMN IF NOT EXISTS normalized_map_number TEXT;
ALTER TABLE sheriff_sales ADD COLUMN IF NOT EXISTS sale_attorney TEXT;
ALTER TABLE sheriff_sales ADD COLUMN IF NOT EXISTS sale_result TEXT;

CREATE INDEX IF NOT EXISTS idx_sheriff_sales_pa_map_number
    ON sheriff_sales (state, county, normalized_map_number)
    WHERE state = 'PA';

COMMIT;
