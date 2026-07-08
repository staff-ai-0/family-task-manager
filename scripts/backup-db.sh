#!/usr/bin/env bash
#
# Scheduled backup — DB dump + uploads-volume archive + optional offsite push.
# Canonical target: on-prem 10.1.0.91 (rootless podman, user jc). Runs via the
# USER-level systemd timer in scripts/systemd/family-onprem-backup.timer, or
# cron, or by hand. NEVER invoke podman with sudo on that host (global
# rootless rule — sudo podman corrupts jc's overlay storage).
#
# What it does:
#   1. pg_dumps the postgres container to backups/scheduled/db-<ts>.sql.gz
#      (--clean --if-exists, so restores are idempotent over a populated DB)
#   2. Archives the receipt_uploads volume (gig proof photos, receipt images)
#      to backups/scheduled/uploads-<ts>.tar.gz via rootless
#      `podman volume export` (audit 2026-07-07: uploads were never backed up)
#   3. Prunes local artifacts older than RETENTION_DAYS (default 14)
#   4. If OFFSITE_RCLONE_REMOTE is set (e.g. "b2:family-backups"), pushes both
#      artifacts there with rclone and prunes remote copies older than
#      OFFSITE_RETENTION_DAYS (default 30). Any offsite failure exits non-zero
#      so the systemd unit records it (audit 2026-07-07 CRITICAL: no offsite).
#
# Env overrides:
#   APP_DIR                 default /home/jc/family-task-manager
#   COMPOSE_FILE            default docker-compose.onprem.yml
#   COMPOSE_CMD             default "podman compose"
#   PG_SERVICE              compose service name of postgres (default
#                           "postgres"; local dev compose names it "db")
#   BACKUP_DIR              default backups/scheduled (relative to APP_DIR)
#   RETENTION_DAYS          local retention, default 14
#   UPLOADS_VOLUME          override uploads-volume autodetection
#   SKIP_UPLOADS=1          skip the uploads archive (e.g. docker-only host)
#   OFFSITE_RCLONE_REMOTE   rclone remote[:path], e.g. "b2:family-backups".
#                           Unset = no offsite push (loud warning).
#   OFFSITE_RETENTION_DAYS  remote retention, default 30
#
# GCP rollback host (Docker CE, archival only) override:
#   COMPOSE_FILE=docker-compose.gcp.yml COMPOSE_CMD="sudo docker compose" \
#     SKIP_UPLOADS=1 ./scripts/backup-db.sh
#
set -euo pipefail

APP_DIR="${APP_DIR:-/home/jc/family-task-manager}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.onprem.yml}"
COMPOSE_CMD="${COMPOSE_CMD:-podman compose}"
PG_SERVICE="${PG_SERVICE:-postgres}"
BACKUP_DIR="${BACKUP_DIR:-backups/scheduled}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
OFFSITE_RCLONE_REMOTE="${OFFSITE_RCLONE_REMOTE:-}"
OFFSITE_RETENTION_DAYS="${OFFSITE_RETENTION_DAYS:-30}"

cd "$APP_DIR"

# Only POSTGRES_USER / POSTGRES_DB are needed from the deployed .env. Do NOT
# `source` the whole file: values with unquoted spaces (e.g. SMTP_FROM_NAME)
# make bash treat the rest of the line as a command.
env_get() {
    local v
    v="$(sed -n "s/^${1}=//p" .env | tail -1)"
    v="${v%\"}"; v="${v#\"}"
    echo "$v"
}
POSTGRES_USER="${POSTGRES_USER:-$(env_get POSTGRES_USER)}"
POSTGRES_DB="${POSTGRES_DB:-$(env_get POSTGRES_DB)}"
if [[ -z "$POSTGRES_USER" || -z "$POSTGRES_DB" ]]; then
    echo "[backup-db] ERROR: POSTGRES_USER / POSTGRES_DB not found in .env" >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"
TS="$(date +%Y%m%d-%H%M%S)"
OUT="${BACKUP_DIR}/db-${TS}.sql.gz"

# ── 1. Database dump ────────────────────────────────────────────────────────
echo "[backup-db] dumping ${POSTGRES_DB} -> ${OUT}"
# shellcheck disable=SC2086
$COMPOSE_CMD --env-file .env -f "$COMPOSE_FILE" exec -T "$PG_SERVICE" \
    pg_dump --clean --if-exists -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "$OUT"
echo "[backup-db] wrote ${OUT} ($(du -h "$OUT" | cut -f1))"

# ── 2. Uploads volume archive ───────────────────────────────────────────────
# Resolve the compose-managed volume name (<project>_receipt_uploads): the
# project prefix differs between local dev and the on-prem deploy, so match
# against `podman volume ls` instead of hardcoding.
resolve_uploads_volume() {
    if [[ -n "${UPLOADS_VOLUME:-}" ]]; then
        echo "$UPLOADS_VOLUME"
        return 0
    fi
    local candidates guess
    candidates="$(podman volume ls --format '{{.Name}}' | grep -E '(^|_)receipt_uploads$' || true)"
    # Prefer the compose project name (defaults to the app dir basename).
    guess="${COMPOSE_PROJECT:-$(basename "$PWD")}_receipt_uploads"
    if echo "$candidates" | grep -qx "$guess"; then
        echo "$guess"
        return 0
    fi
    if [[ "$(echo "$candidates" | grep -c . || true)" == "1" ]]; then
        echo "$candidates"
        return 0
    fi
    return 1
}

UPLOADS_OUT=""
if [[ "${SKIP_UPLOADS:-0}" == "1" ]]; then
    echo "[backup-db] SKIP_UPLOADS=1 — not archiving the uploads volume"
elif ! command -v podman >/dev/null 2>&1; then
    echo "[backup-db] ERROR: podman not found — cannot archive the uploads volume." >&2
    echo "            Set SKIP_UPLOADS=1 (docker-only host) or install podman." >&2
    exit 1
else
    if ! VOL="$(resolve_uploads_volume)"; then
        echo "[backup-db] ERROR: cannot resolve the receipt_uploads volume name." >&2
        echo "            Candidates found:" >&2
        podman volume ls --format '{{.Name}}' | grep -E '(^|_)receipt_uploads$' >&2 || echo "            (none)" >&2
        echo "            Set UPLOADS_VOLUME=<name> explicitly and re-run." >&2
        exit 1
    fi
    UPLOADS_OUT="${BACKUP_DIR}/uploads-${TS}.tar.gz"
    echo "[backup-db] archiving uploads volume ${VOL} -> ${UPLOADS_OUT}"
    podman volume export "$VOL" | gzip > "$UPLOADS_OUT"
    echo "[backup-db] wrote ${UPLOADS_OUT} ($(du -h "$UPLOADS_OUT" | cut -f1))"
fi

# ── 3. Local retention ──────────────────────────────────────────────────────
find "$BACKUP_DIR" \( -name 'db-*.sql.gz' -o -name 'uploads-*.tar.gz' \) \
    -type f -mtime "+${RETENTION_DAYS}" -print -delete

# ── 4. Offsite push (rclone) ────────────────────────────────────────────────
if [[ -n "$OFFSITE_RCLONE_REMOTE" ]]; then
    if ! command -v rclone >/dev/null 2>&1; then
        echo "[backup-db] ERROR: OFFSITE_RCLONE_REMOTE='${OFFSITE_RCLONE_REMOTE}' is set but rclone is not installed." >&2
        echo "            Install it (RHEL: sudo dnf install -y rclone; or https://rclone.org/install/)" >&2
        echo "            then configure the remote AS USER jc (no sudo): rclone config" >&2
        exit 1
    fi
    DEST="${OFFSITE_RCLONE_REMOTE}/scheduled"
    echo "[backup-db] offsite: pushing $(basename "$OUT") -> ${DEST}"
    if ! rclone copy "$OUT" "$DEST"; then
        echo "[backup-db] ERROR: offsite push of ${OUT} to ${DEST} FAILED — backups are on-host only!" >&2
        exit 1
    fi
    if [[ -n "$UPLOADS_OUT" ]]; then
        echo "[backup-db] offsite: pushing $(basename "$UPLOADS_OUT") -> ${DEST}"
        if ! rclone copy "$UPLOADS_OUT" "$DEST"; then
            echo "[backup-db] ERROR: offsite push of ${UPLOADS_OUT} to ${DEST} FAILED" >&2
            exit 1
        fi
    fi
    echo "[backup-db] offsite: pruning ${DEST} copies older than ${OFFSITE_RETENTION_DAYS}d"
    if ! rclone delete --min-age "${OFFSITE_RETENTION_DAYS}d" "$DEST"; then
        echo "[backup-db] ERROR: offsite prune of ${DEST} FAILED" >&2
        exit 1
    fi
    echo "[backup-db] offsite push OK -> ${DEST}"
else
    echo "[backup-db] WARNING: OFFSITE_RCLONE_REMOTE not set — backups exist ONLY on this host." >&2
    echo "            See scripts/systemd/README.md for the rclone offsite setup." >&2
fi

echo "[backup-db] done ($(find "$BACKUP_DIR" -name 'db-*.sql.gz' | wc -l | tr -d ' ') dumps, $(find "$BACKUP_DIR" -name 'uploads-*.tar.gz' | wc -l | tr -d ' ') uploads archives retained locally)"
