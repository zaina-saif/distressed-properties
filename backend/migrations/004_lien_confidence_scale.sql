BEGIN;

ALTER TABLE property_liens
    ALTER COLUMN survival_confidence TYPE NUMERIC(5, 2)
    USING CASE
        WHEN survival_confidence BETWEEN 0 AND 1
            THEN survival_confidence * 100
        ELSE survival_confidence
    END;

COMMIT;
