-- Preserve the documented beginning of a distress proceeding.  Some public
-- listings expose only a case year, so exact dates and bounded estimates are
-- deliberately stored separately.
ALTER TABLE sheriff_sales
    ADD COLUMN IF NOT EXISTS distress_start_date DATE,
    ADD COLUMN IF NOT EXISTS distress_start_year INTEGER,
    ADD COLUMN IF NOT EXISTS distress_start_basis TEXT;

