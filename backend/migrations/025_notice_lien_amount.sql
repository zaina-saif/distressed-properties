BEGIN;

ALTER TABLE sheriff_sales
    ADD COLUMN IF NOT EXISTS notice_lien_amount NUMERIC(14, 2);

COMMIT;
