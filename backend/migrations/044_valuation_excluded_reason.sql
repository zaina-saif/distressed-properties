-- Properties whose sale is not of a whole home, so no market value applies: a timeshare
-- interest (a fraction of a hotel unit). The Zillow and NYC DOF stages skip them, and the
-- dashboard shows the reason in place of a value (pipeline.load_queens_pipeline sets it).
BEGIN;

ALTER TABLE properties ADD COLUMN IF NOT EXISTS valuation_excluded_reason TEXT;

COMMIT;
