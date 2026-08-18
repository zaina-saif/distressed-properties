BEGIN;

ALTER TABLE properties
    ADD COLUMN IF NOT EXISTS square_feet_source TEXT,
    ADD COLUMN IF NOT EXISTS square_feet_confidence NUMERIC(5, 2),
    ADD COLUMN IF NOT EXISTS square_feet_retrieved_at TIMESTAMPTZ;

ALTER TABLE properties
    DROP CONSTRAINT IF EXISTS properties_square_feet_confidence_check;

ALTER TABLE properties
    ADD CONSTRAINT properties_square_feet_confidence_check
    CHECK (
        square_feet_confidence IS NULL
        OR square_feet_confidence BETWEEN 0 AND 100
    );

COMMIT;
