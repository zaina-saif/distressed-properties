#!/bin/sh
# Apply backend/migrations (mounted at /migrations) in file-name order on first start.
# Local development only (docker compose `db`); production migrations are applied by hand.
set -eu
run() {
  psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER:-postgres}" --dbname "${POSTGRES_DB:-postgres}" \
    ${PGHOST:+--host "$PGHOST"} ${PGPORT:+--port "$PGPORT"} -q "$@"
}
for file in $(ls "${MIGRATIONS_DIR:-/migrations}"/*.sql | sort); do
  if [ "$(basename "$file")" = "003_lien_schema_compatibility.sql" ]; then
    # 003 backfills from columns production's original property_liens table had and a
    # fresh 002 does not create; add them (empty) so it applies to a new database.
    run -c "ALTER TABLE property_liens ADD COLUMN IF NOT EXISTS source TEXT,
            ADD COLUMN IF NOT EXISTS source_document_url TEXT, ADD COLUMN IF NOT EXISTS recording_number TEXT,
            ADD COLUMN IF NOT EXISTS survives_foreclosure BOOLEAN;"
  fi
  echo "applying $(basename "$file")"
  run -f "$file"
done
