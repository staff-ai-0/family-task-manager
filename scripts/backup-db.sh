#!/usr/bin/env bash
#
# Scheduled database backup — runs ON the GCP VM (via the systemd timer in
# scripts/systemd/, or cron, or by hand). pg_dumps the postgres container to a
# gzipped, --clean-able SQL file under backups/scheduled/ and prunes dumps
# older than RETENTION_DAYS.
#
# Off-VM durability (upload to a GCS bucket) is intentionally a TODO — see the
# note at the bottom. This script gives the VM local scheduled backups +
# retention, which it previously lacked entirely (audit M7).
#
# Env overrides: APP_DIR, COMPOSE_FILE, RETENTION_DAYS.
#
set -euo pipefail

APP_DIR="${APP_DIR:-/home/jc/family-task-manager}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.gcp.yml}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
COMPOSE_CMD="${COMPOSE_CMD:-sudo docker compose}"

cd "$APP_DIR"

# POSTGRES_USER / POSTGRES_DB come from the deployed .env.
set -a
# shellcheck disable=SC1091
source .env
set +a

mkdir -p backups/scheduled
TS="$(date +%Y%m%d-%H%M%S)"
OUT="backups/scheduled/db-${TS}.sql.gz"

echo "[backup-db] dumping ${POSTGRES_DB} -> ${OUT}"
# --clean --if-exists makes the dump idempotent to restore over a populated DB.
# shellcheck disable=SC2086
$COMPOSE_CMD --env-file .env -f "$COMPOSE_FILE" exec -T postgres \
    pg_dump --clean --if-exists -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "$OUT"

echo "[backup-db] wrote ${OUT} ($(du -h "$OUT" | cut -f1))"

# Retention: delete gzipped dumps older than RETENTION_DAYS.
find backups/scheduled -name 'db-*.sql.gz' -type f -mtime "+${RETENTION_DAYS}" -print -delete

echo "[backup-db] done ($(find backups/scheduled -name 'db-*.sql.gz' | wc -l | tr -d ' ') dumps retained)"

# TODO (off-VM durability): after writing $OUT, upload to a GCS bucket, e.g.
#   gsutil cp "$OUT" "gs://<family-backups-bucket>/$(basename "$OUT")"
# The VM service account needs roles/storage.objectCreator on that bucket.
