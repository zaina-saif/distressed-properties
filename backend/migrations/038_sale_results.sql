-- Sale results: the winning bid and who bought, parsed from the sale's own
-- page (CivilView "Status History" amounts) or its status text ("SOLD: 3RD
-- PARTY FOR $68,100"). Filled by pipeline/sale_results.py; raw text is kept on
-- sheriff_sales.description_text and sheriff_sale_status_history.raw_status.
BEGIN;

ALTER TABLE sheriff_sales
    ADD COLUMN IF NOT EXISTS sold_amount NUMERIC(14, 2),
    ADD COLUMN IF NOT EXISTS sold_buyer TEXT
        CHECK (sold_buyer IN ('third_party', 'plaintiff', 'cwpp', 'not_stated')),
    ADD COLUMN IF NOT EXISTS sold_on DATE,
    ADD COLUMN IF NOT EXISTS sold_raw_status TEXT;

CREATE INDEX IF NOT EXISTS sheriff_sales_sold_on_idx
    ON sheriff_sales (state, county, sold_on)
    WHERE sold_on IS NOT NULL;

COMMIT;
