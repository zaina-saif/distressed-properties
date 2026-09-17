BEGIN;

ALTER TABLE public_property_snapshots
    ADD COLUMN IF NOT EXISTS house_number_unavailable BOOLEAN NOT NULL DEFAULT FALSE;

COMMIT;
