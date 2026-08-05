#!/usr/bin/env bash
#
# Restore drill — prove the newest backup can actually be restored.
#
# Restores the newest scheduled dump into a THROWAWAY postgres container and
# compares it against the live database. The live DB is only ever read
# (SELECT count(*)); nothing here can write to it. Safe to run on prod, and
# meant to be: a backup nobody has restored is not a backup.
#
#   ./scripts/restore-drill.sh                 # newest dump in backups/scheduled
#   ./scripts/restore-drill.sh <dump.sql.gz>   # a specific one
#
# Exits non-zero if the restore errors, if the schema comes back smaller than
# live, or if any compared table is short by more than DRIFT_TOLERANCE rows.
#
# Why this exists: restore-db.sh pre-created a hardcoded `jarvis_mcp` role
# because the 2026-07-07 drill hit it. The monitoring stack later added
# `grafana_ro`, whose GRANT sorts first, and nothing re-ran that drill — so
# from then until 2026-08-04 every nightly backup looked healthy while
# restoring exactly zero tables (--single-transaction rolled the whole thing
# back on the missing role). This script is what makes that regression loud.
#
# Env overrides: APP_DIR, COMPOSE_FILE, COMPOSE_CMD, PG_SERVICE, PG_IMAGE,
#                LIVE_DB_CONTAINER, DRIFT_TOLERANCE, KEEP_CONTAINER=1
#
set -uo pipefail

APP_DIR="${APP_DIR:-/home/jc/family-task-manager}"
PG_IMAGE="${PG_IMAGE:-docker.io/library/postgres:15-alpine}"
LIVE_DB_CONTAINER="${LIVE_DB_CONTAINER:-family_onprem_db}"
DRILL_CONTAINER="${DRILL_CONTAINER:-family_restore_drill}"
# Live rows can legitimately be added between the dump and the drill, so the
# restored copy is allowed to be BEHIND live by a little. It is never allowed
# to be ahead, and a table that comes back empty is always a failure.
DRIFT_TOLERANCE="${DRIFT_TOLERANCE:-25}"

cd "$APP_DIR" || { echo "[drill] cannot cd to $APP_DIR" >&2; exit 1; }

env_get() {
    local v
    v="$(sed -n "s/^${1}=//p" .env | tail -1)"
    v="${v%\"}"; v="${v#\"}"
    echo "$v"
}
POSTGRES_USER="${POSTGRES_USER:-$(env_get POSTGRES_USER)}"
POSTGRES_DB="${POSTGRES_DB:-$(env_get POSTGRES_DB)}"

DUMP="${1:-$(ls -t backups/scheduled/db-*.sql.gz 2>/dev/null | head -1)}"
if [[ -z "$DUMP" || ! -f "$DUMP" ]]; then
    echo "[drill] FAIL: no dump found (looked in backups/scheduled/db-*.sql.gz)" >&2
    exit 1
fi
GLOBALS="${DUMP/db-/globals-}"
[[ -f "$GLOBALS" ]] || GLOBALS=""

echo "[drill] dump    : $DUMP ($(du -h "$DUMP" | cut -f1))"
echo "[drill] globals : ${GLOBALS:-<none — pre-2026-08-04 backup, roles will be derived>}"

cleanup() {
    if [[ "${KEEP_CONTAINER:-0}" != "1" ]]; then
        podman rm -f "$DRILL_CONTAINER" >/dev/null 2>&1
    fi
}
trap cleanup EXIT

podman rm -f "$DRILL_CONTAINER" >/dev/null 2>&1
if ! podman run -d --name "$DRILL_CONTAINER" \
        -e POSTGRES_PASSWORD=drill-throwaway \
        -e POSTGRES_USER="$POSTGRES_USER" \
        -e POSTGRES_DB="$POSTGRES_DB" \
        "$PG_IMAGE" >/dev/null; then
    echo "[drill] FAIL: could not start the scratch container" >&2
    exit 1
fi

# Readiness is NOT just pg_isready: the postgres image runs a TEMPORARY server
# on the unix socket while initdb runs, then shuts it down and starts the real
# one. Polling pg_isready alone catches that temp server, breaks the wait, and
# the next command then fails against a server that is mid-restart. So wait for
# the entrypoint's init-complete marker FIRST, and only then poll pg_isready.
#
# The marker is matched against a CAPTURED string, not `podman logs | grep -q`:
# under `set -o pipefail`, grep -q exits at the first match and SIGPIPEs the
# writer, so the pipeline reports failure even though the pattern WAS found.
# That made this wait fail roughly one run in two.
READY=0
for _ in $(seq 1 90); do
    LOGS="$(podman logs "$DRILL_CONTAINER" 2>&1 || true)"
    if [[ "$LOGS" == *"PostgreSQL init process complete"* ]]; then
        READY=1
        break
    fi
    if [[ "$(podman inspect "$DRILL_CONTAINER" --format '{{.State.Running}}' 2>/dev/null)" != "true" ]]; then
        echo "[drill] FAIL: scratch container exited during init" >&2
        podman logs "$DRILL_CONTAINER" 2>&1 | tail -15 >&2
        exit 1
    fi
    sleep 1
done
if (( ! READY )); then
    echo "[drill] FAIL: scratch postgres never finished initdb" >&2
    podman logs "$DRILL_CONTAINER" 2>&1 | tail -15 >&2
    exit 1
fi
for _ in $(seq 1 30); do
    podman exec "$DRILL_CONTAINER" pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1 && break
    sleep 1
done
if ! podman exec "$DRILL_CONTAINER" pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; then
    echo "[drill] FAIL: scratch postgres never became ready after initdb" >&2
    podman logs "$DRILL_CONTAINER" 2>&1 | tail -15 >&2
    exit 1
fi

# *_psql pass stdin through (the restore pipes a dump into drill_psql).
drill_psql() { podman exec -i "$DRILL_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"; }
live_psql()  { podman exec -i "$LIVE_DB_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"; }
# *_q are for -c/-tAc queries and must NOT inherit stdin: `podman exec -i`
# drains it, which inside a `while read` loop eats the list being iterated.
drill_q() { drill_psql "$@" </dev/null; }
live_q()  { live_psql  "$@" </dev/null; }

# ── Roles ───────────────────────────────────────────────────────────────────
if [[ -n "$GLOBALS" ]]; then
    echo "[drill] applying globals (roles)"
    gunzip -c "$GLOBALS" | drill_psql -q >/dev/null 2>&1
else
    # Mirror restore-db.sh's fallback so the drill exercises the same path an
    # operator would actually take with a backup of this vintage.
    echo "[drill] deriving roles from the dump (no globals file)"
    gunzip -c "$DUMP" | awk '
        /^COPY .* FROM stdin;$/ { in_copy = 1; next }
        in_copy                 { if ($0 == "\\.") in_copy = 0; next }
        /^GRANT /   { if (match($0, / TO [^;]+;/))   emit(substr($0, RSTART + 4,  RLENGTH - 5)) }
        /^REVOKE /  { if (match($0, / FROM [^;]+;/)) emit(substr($0, RSTART + 6,  RLENGTH - 7)) }
                    { if (match($0, / OWNER TO [^;]+;/)) emit(substr($0, RSTART + 10, RLENGTH - 11)) }
        function emit(s,   n, parts, i, r) {
            sub(/ WITH GRANT OPTION$/, "", s)
            n = split(s, parts, ",")
            for (i = 1; i <= n; i++) {
                r = parts[i]; gsub(/^[ \t]+|[ \t]+$/, "", r); gsub(/^"|"$/, "", r)
                if (r != "") print r
            }
        }' | sort -u | while IFS= read -r role; do
            case "$role" in
                PUBLIC|public|CURRENT_USER|SESSION_USER|CURRENT_ROLE|pg_*|"$POSTGRES_USER") continue ;;
            esac
            drill_q -qc "CREATE ROLE \"${role//\"/\"\"}\" NOLOGIN" >/dev/null 2>&1
        done
fi

# ── Restore ─────────────────────────────────────────────────────────────────
echo "[drill] restoring (--single-transaction, ON_ERROR_STOP=1) ..."
RESTORE_LOG="$(mktemp)"
gunzip -c "$DUMP" | drill_psql --single-transaction -v ON_ERROR_STOP=1 -q >"$RESTORE_LOG" 2>&1
RC=$?
if [[ $RC -ne 0 ]] || grep -qi '^ERROR' "$RESTORE_LOG"; then
    echo "[drill] FAIL: restore did not complete cleanly (rc=$RC)" >&2
    grep -i '^ERROR\|^psql:' "$RESTORE_LOG" | head -10 >&2
    rm -f "$RESTORE_LOG"
    exit 1
fi
rm -f "$RESTORE_LOG"

# ── Compare ─────────────────────────────────────────────────────────────────
TABLE_Q="SELECT count(*) FROM information_schema.tables WHERE table_schema='public'"
R_TABLES="$(drill_q -tAc "$TABLE_Q" 2>/dev/null | tr -d '[:space:]')"
L_TABLES="$(live_q  -tAc "$TABLE_Q" 2>/dev/null | tr -d '[:space:]')"
echo "[drill] tables: restored=${R_TABLES} live=${L_TABLES}"
if [[ -z "$R_TABLES" || "$R_TABLES" == "0" ]]; then
    echo "[drill] FAIL: restored schema is EMPTY — this backup recovers nothing" >&2
    exit 1
fi
if [[ -n "$L_TABLES" ]] && (( R_TABLES < L_TABLES )); then
    echo "[drill] FAIL: restored schema has fewer tables than live" >&2
    exit 1
fi

FAILED=0
for t in users families task_assignments budget_transactions cash_transactions subscription_plans; do
    R="$(drill_q -tAc "SELECT count(*) FROM ${t}" 2>/dev/null | tr -d '[:space:]')"
    L="$(live_q  -tAc "SELECT count(*) FROM ${t}" 2>/dev/null | tr -d '[:space:]')"
    [[ -z "$R" ]] && R=missing
    [[ -z "$L" ]] && L=missing
    printf '[drill] %-22s restored=%-8s live=%s\n' "$t" "$R" "$L"
    if [[ "$R" == "missing" ]]; then
        echo "[drill]   ^ FAIL: table absent from the restored copy" >&2; FAILED=1; continue
    fi
    if [[ "$L" != "missing" ]]; then
        if (( L > 0 && R == 0 )); then
            echo "[drill]   ^ FAIL: empty in the restored copy but populated live" >&2; FAILED=1
        elif (( L - R > DRIFT_TOLERANCE )); then
            echo "[drill]   ^ FAIL: short by $((L - R)) rows (tolerance ${DRIFT_TOLERANCE})" >&2; FAILED=1
        fi
    fi
done

V_R="$(drill_q -tAc 'SELECT version_num FROM alembic_version' 2>/dev/null | tr -d '[:space:]')"
V_L="$(live_q  -tAc 'SELECT version_num FROM alembic_version' 2>/dev/null | tr -d '[:space:]')"
echo "[drill] alembic: restored=${V_R:-missing} live=${V_L:-missing}"
if [[ -z "$V_R" ]]; then
    echo "[drill] FAIL: no alembic_version in the restored copy" >&2; FAILED=1
fi

if (( FAILED )); then
    echo "[drill] RESULT: FAIL — this backup does not restore correctly" >&2
    exit 1
fi
echo "[drill] RESULT: PASS — ${DUMP} restores clean and matches live"
