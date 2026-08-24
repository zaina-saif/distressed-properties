BEGIN;

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX IF NOT EXISTS idx_properties_normalized_address_trgm
    ON properties USING GIN (normalized_address gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_properties_street_address_trgm
    ON properties USING GIN (street_address gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_properties_city_trgm
    ON properties USING GIN (city gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_properties_county_lower
    ON properties (LOWER(county));
CREATE INDEX IF NOT EXISTS idx_properties_zip_code
    ON properties (zip_code);

CREATE INDEX IF NOT EXISTS idx_sheriff_sales_number_trgm
    ON sheriff_sales USING GIN (sheriff_number gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_sheriff_sales_court_case_trgm
    ON sheriff_sales USING GIN (court_case_number gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_sheriff_sales_plaintiff_trgm
    ON sheriff_sales USING GIN (plaintiff gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_sheriff_sales_defendant_trgm
    ON sheriff_sales USING GIN (defendant gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_sheriff_sales_status_lower_date
    ON sheriff_sales (LOWER(current_status), current_sale_date);

COMMIT;
