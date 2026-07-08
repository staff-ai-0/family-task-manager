#!/usr/bin/env bash
#
# Restore the database and/or the uploads volume from backups produced by
# backup-db.sh (or any plain pg_dump, gzipped or not).
#
# Canonical target: on-prem 10.1.0.91 (rootless podman, user jc — NEVER sudo
# podman). Defaults below match that host.
#
#   ./scripts/restore-db.sh backups/scheduled/db-YYYYMMDD-HHMMSS.sql.gz
#   ./scripts/restore-db.sh --uploads backups/scheduled/uploads-YYYYMMDD-HHMMSS.tar.gz
#   ./scripts/restore-db.sh --uploads <uploads.tar.gz> <db.sql.gz>   # both
#
# DESTRUCTIVE: with --clean dumps this drops and recreates objects, replacing
# current data; --uploads overwrites files in the receipt_uploads volume.
# Requires a typed confirmation. The DB restore runs in a SINGLE transaction
# (psql --single-transaction + ON_ERROR_STOP): a mid-stream failure rolls
# back and leaves the current database unchanged.
#
# GCP rollback host (Docker CE — archival only, do NOT use for prod) override:
#   COMPOSE_FILE=docker-compose.gcp.yml COMPOSE_CMD="sudo docker compose" \
#     ./scripts/restore-db.sh <dump>
#
# Env overrides: APP_DIR, COMPOSE_FILE, COMPOSE_CMD, PG_SERVICE, UPLOADS_VOLUME.
#
set -euo pipefail

APP_DIR="${APP_DIR:-/home/jc/family-task-manager}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.onprem.yml}"
COMPOSE_CMD="${COMPOSE_CMD:-podman compose}"
PG_SERVICE="${PG_SERVICE:-postgres}"

usage() {
    echo "usage: $0 [--uploads <uploads.tar[.gz]>] [<backup.sql|backup.sql.gz>]" >&2
    echo "available:" >&2
    ls -1t backups/scheduled/*.sql.gz backups/scheduled/*.tar.gz backups/pre-deploy/*.sql 2>/dev/null | head -20 >&2 || true
    exit 1
}

cd "$APP_DIR"

DB_FILE=""
UPLOADS_FILE=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --uploads)
            UPLOADS_FILE="${2:-}"
            [[ -n "$UPLOADS_FILE" ]] || { echo "--uploads needs an archive path" >&2; usage; }
            shift 2
            ;;
        -h|--help)
            usage
            ;;
        -*)
            echo "unknown option: $1" >&2
            usage
            ;;
        *)
            DB_FILE="$1"
            shift
            ;;
    esac
done

if [[ -z "$DB_FILE" && -z "$UPLOADS_FILE" ]]; then
    usage
fi
if [[ -n "$DB_FILE" && ! -f "$DB_FILE" ]]; then
    echo "not found: $DB_FILE" >&2
    exit 1
fi
if [[ -n "$UPLOADS_FILE" && ! -f "$UPLOADS_FILE" ]]; then
    echo "not found: $UPLOADS_FILE" >&2
    exit 1
fi

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
    echo "[restore-db] ERROR: POSTGRES_USER / POSTGRES_DB not found in .env" >&2
    exit 1
fi

# Same autodetection as backup-db.sh: compose project prefix differs between
# local dev and the on-prem deploy.
resolve_uploads_volume() {
    if [[ -n "${UPLOADS_VOLUME:-}" ]]; then
        echo "$UPLOADS_VOLUME"
        return 0
    fi
    local candidates guess
    candidates="$(podman volume ls --format '{{.Name}}' | grep -E '(^|_)receipt_uploads$' || true)"
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

VOL=""
if [[ -n "$UPLOADS_FILE" ]]; then
    if ! command -v podman >/dev/null 2>&1; then
        echo "podman not found — --uploads restore requires rootless podman" >&2
        exit 1
    fi
    if ! VOL="$(resolve_uploads_volume)"; then
        echo "cannot resolve the receipt_uploads volume name; set UPLOADS_VOLUME=<name>" >&2
        exit 1
    fi
fi

echo "About to RESTORE:"
if [[ -n "$DB_FILE" ]]; then
    echo "  database '${POSTGRES_DB}' from $DB_FILE ($(du -h "$DB_FILE" | cut -f1))"
fi
if [[ -n "$UPLOADS_FILE" ]]; then
    echo "  uploads volume '${VOL}' from $UPLOADS_FILE ($(du -h "$UPLOADS_FILE" | cut -f1))"
fi
echo "This OVERWRITES the current contents and cannot be undone."
read -r -p "Type 'restore' to confirm: " ans
if [[ "$ans" != "restore" ]]; then
    echo "aborted"
    exit 1
fi

if [[ -n "$DB_FILE" ]]; then
    # pg_dump does not include cluster-level roles; dumps carry GRANTs to
    # jarvis_mcp, which aborts a fresh-cluster restore under ON_ERROR_STOP
    # (found in the 2026-07-07 restore drill). Pre-create it if missing —
    # NOLOGIN is enough for the GRANTs; if Jarvis MCP HTTP is enabled, set
    # its LOGIN password afterwards per docs/JARVIS_MCP.md.
    # shellcheck disable=SC2086
    $COMPOSE_CMD --env-file .env -f "$COMPOSE_FILE" exec -T "$PG_SERVICE" \
        psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
        "DO \$\$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'jarvis_mcp') THEN CREATE ROLE jarvis_mcp NOLOGIN; END IF; END \$\$;"

    if [[ "$DB_FILE" == *.gz ]]; then
        DECOMP=(gunzip -c "$DB_FILE")
    else
        DECOMP=(cat "$DB_FILE")
    fi
    # --single-transaction makes the restore atomic: backup-db.sh produces a
    # plain pg_dump (--clean --if-exists, no BEGIN/COMMIT of its own), so the
    # whole script — DROPs included — runs in one transaction and a mid-stream
    # failure ROLLS BACK, leaving the current DB untouched instead of
    # partially dropped. ON_ERROR_STOP aborts on the first error so the
    # rollback actually fires.
    # shellcheck disable=SC2086
    "${DECOMP[@]}" | $COMPOSE_CMD --env-file .env -f "$COMPOSE_FILE" exec -T "$PG_SERVICE" \
        psql --single-transaction -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"
    echo "[restore-db] database restore complete"
fi

if [[ -n "$UPLOADS_FILE" ]]; then
    echo "[restore-db] importing $UPLOADS_FILE into volume ${VOL}"
    if [[ "$UPLOADS_FILE" == *.gz ]]; then
        gunzip -c "$UPLOADS_FILE" | podman volume import "$VOL" -
    else
        podman volume import "$VOL" "$UPLOADS_FILE"
    fi
    # Rule 4: rootless volume ownership must match the in-container appuser
    # (UID/GID 1000), same as deploy-onprem.sh does at deploy time.
    if ! podman unshare chown -R 1000:1000 \
        "$(podman volume inspect "$VOL" --format '{{.Mountpoint}}')" 2>/dev/null; then
        echo "[restore-db] WARNING: could not chown the volume (remote podman client?)." >&2
        echo "             On the host, run: podman unshare chown -R 1000:1000 \$(podman volume inspect ${VOL} --format '{{.Mountpoint}}')" >&2
    fi
    echo "[restore-db] uploads restore complete"
fi

echo "[restore-db] done"
