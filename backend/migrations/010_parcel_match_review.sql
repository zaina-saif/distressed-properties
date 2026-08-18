BEGIN;

CREATE TABLE IF NOT EXISTS property_parcel_candidates (
    id BIGSERIAL PRIMARY KEY,
    property_id UUID NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    rank SMALLINT NOT NULL,
    match_score NUMERIC(6,5) NOT NULL,
    municipality_code CHAR(4) NOT NULL,
    block TEXT NOT NULL,
    lot TEXT NOT NULL,
    qualifier TEXT NOT NULL DEFAULT '',
    property_location TEXT NOT NULL,
    parcel_features JSONB NOT NULL,
    source_hash CHAR(64) NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (review_status IN ('PENDING','APPROVED','REJECTED')),
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(property_id, source_hash)
);

CREATE INDEX IF NOT EXISTS idx_parcel_candidates_review
    ON property_parcel_candidates(review_status, property_id, rank);

COMMIT;
