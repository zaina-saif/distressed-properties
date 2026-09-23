BEGIN;

ALTER TABLE sheriff_sales
    ADD COLUMN IF NOT EXISTS judgment_amount_as_of_date DATE,
    ADD COLUMN IF NOT EXISTS judgment_source_url TEXT;

COMMIT;
