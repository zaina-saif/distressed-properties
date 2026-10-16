-- The case data a summary is built from (pipeline.ny_case_summary.build_summary), so the
-- API rebuilds it with the current date: the next auction, dates gone by and the stages
-- stay right between loads.
BEGIN;

ALTER TABLE ny_court_case_summaries ADD COLUMN IF NOT EXISTS inputs JSONB;

COMMIT;
