#!/usr/bin/env bash
#
# Restore the database from a backup produced by backup-db.sh (or any plain
# pg_dump, gzipped or not). Runs ON the GCP VM.
#
#   ./scripts/restore-db.sh backups/scheduled/db-YYYYMMDD-HHMMSS.sql.gz
#
# DESTRUCTIVE: with --clean dumps this drops and recreates objects, replacing
# current data. Requires a typed confirmation.
#
# Env overrides: APP_DIR, COMPOSE_FILE.
#
set -euo pipefail

APP_DIR="${APP_DIR:-/home/jc/family-task-manager}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.gcp.yml}"
COMPOSE_CMD="${COMPOSE_CMD:-sudo docker compose}"

cd "$APP_DIR"

FILE="${1:-}"
if [[ -z "$FILE" ]]; then
    echo "usage: $0 <backup.sql|backup.sql.gz>" >&2
    echo "available:" >&2
    ls -1t backups/scheduled/*.sql.gz backups/pre-deploy/*.sql 2>/dev/null | head -20 >&2 || true
    exit 1
fi
if [[ ! -f "$FILE" ]]; then
    echo "not found: $FILE" >&2
    exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

echo "About to RESTORE database '${POSTGRES_DB}' from:"
echo "    $FILE ($(du -h "$FILE" | cut -f1))"
echo "This OVERWRITES the current database contents and cannot be undone."
read -r -p "Type 'restore' to confirm: " ans
if [[ "$ans" != "restore" ]]; then
    echo "aborted"
    exit 1
fi

if [[ "$FILE" == *.gz ]]; then
    DECOMP=(gunzip -c "$FILE")
else
    DECOMP=(cat "$FILE")
fi

# shellcheck disable=SC2086
"${DECOMP[@]}" | $COMPOSE_CMD --env-file .env -f "$COMPOSE_FILE" exec -T postgres \
    psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"

echo "[restore-db] restore complete"
