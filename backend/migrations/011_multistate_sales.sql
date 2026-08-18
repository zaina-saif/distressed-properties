BEGIN;
ALTER TABLE sheriff_sales ADD COLUMN IF NOT EXISTS state CHAR(2);
UPDATE sheriff_sales SET state='NJ' WHERE state IS NULL;
ALTER TABLE sheriff_sales ALTER COLUMN state SET NOT NULL;
ALTER TABLE sheriff_sales DROP CONSTRAINT IF EXISTS sheriff_sales_county_sheriff_number_key;
CREATE UNIQUE INDEX IF NOT EXISTS uq_sheriff_sales_state_county_number
  ON sheriff_sales(state,county,sheriff_number);
ALTER TABLE raw_scrape_records ADD COLUMN IF NOT EXISTS state CHAR(2);
UPDATE raw_scrape_records SET state='NJ' WHERE state IS NULL;
ALTER TABLE raw_scrape_records ALTER COLUMN state SET NOT NULL;
COMMIT;
