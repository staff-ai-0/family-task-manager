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
    if [[ "$DB_FILE" == *.gz ]]; then
        DECOMP=(gunzip -c "$DB_FILE")
    else
        DECOMP=(cat "$DB_FILE")
    fi

    # ── Role preflight ──────────────────────────────────────────────────────
    # pg_dump carries GRANTs to cluster-level roles but never the roles
    # themselves, so a restore into a cluster that lacks one dies on
    # `role "<x>" does not exist` — and because the restore runs
    # --single-transaction, that rolls the WHOLE restore back and recovers
    # nothing.
    #
    # This used to hardcode `jarvis_mcp` (the role the 2026-07-07 drill hit).
    # The monitoring stack later added `grafana_ro`, whose GRANT sorts BEFORE
    # the jarvis_mcp ones, and the hardcoded preflight sailed straight past it:
    # the 2026-08-04 drill restored prod's newest dump into a scratch cluster
    # and ended with tables=0. A hardcoded list is only correct until the next
    # role, so derive the set from the dump being restored.
    #
    # Preferred source is the sibling globals-<ts>.sql[.gz] that backup-db.sh
    # now writes (pg_dumpall --globals-only): real CREATE ROLE statements with
    # attributes, passwords and memberships intact. Backups taken before that
    # existed have no globals file, so fall back to scanning the dump's own
    # GRANT/REVOKE/OWNER TO statements and creating what is missing as NOLOGIN
    # — enough to make the GRANTs apply, but any role that needs LOGIN comes
    # back unable to authenticate until its password is reset.
    GLOBALS_FILE=""
    _cand="${DB_FILE/db-/globals-}"
    for _g in "$_cand" "${_cand%.gz}"; do
        if [[ "$_g" != "$DB_FILE" && -f "$_g" ]]; then
            GLOBALS_FILE="$_g"
            break
        fi
    done

    # psql_exec passes stdin through (the globals restore pipes into it).
    psql_exec() {
        # shellcheck disable=SC2086
        $COMPOSE_CMD --env-file .env -f "$COMPOSE_FILE" exec -T "$PG_SERVICE" \
            psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"
    }
    # psql_query is for -c/-tAc calls and MUST NOT inherit stdin: `exec -T`
    # drains whatever it is given, so calling it inside a `while read` loop
    # would swallow the very list being iterated.
    psql_query() { psql_exec "$@" </dev/null; }
    # Globals are applied WITHOUT ON_ERROR_STOP on purpose. The target cluster
    # always already has POSTGRES_USER (the postgres image creates it), so the
    # globals file's first `CREATE ROLE familyapp;` is guaranteed to error —
    # and under ON_ERROR_STOP that would abort before reaching grafana_ro or
    # jarvis_mcp, quietly restoring none of the roles the dump actually needs.
    psql_globals() {
        # shellcheck disable=SC2086
        $COMPOSE_CMD --env-file .env -f "$COMPOSE_FILE" exec -T "$PG_SERVICE" \
            psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"
    }

    # Role names referenced by the dump. Skips COPY data blocks so a row whose
    # text happens to start with "GRANT " cannot invent a role.
    dump_roles() {
        "${DECOMP[@]}" | awk '
            /^COPY .* FROM stdin;$/ { in_copy = 1; next }
            in_copy                 { if ($0 == "\\.") in_copy = 0; next }
            /^GRANT /   { if (match($0, / TO [^;]+;/))   emit(substr($0, RSTART + 4,  RLENGTH - 5)) }
            /^REVOKE /  { if (match($0, / FROM [^;]+;/)) emit(substr($0, RSTART + 6,  RLENGTH - 7)) }
                        { if (match($0, / OWNER TO [^;]+;/)) emit(substr($0, RSTART + 10, RLENGTH - 11)) }
            /^ALTER DEFAULT PRIVILEGES/ {
                if (match($0, /FOR ROLE [A-Za-z0-9_"$]+/)) emit(substr($0, RSTART + 9, RLENGTH - 9))
            }
            function emit(s,   n, parts, i, r) {
                sub(/ WITH GRANT OPTION$/, "", s)
                n = split(s, parts, ",")
                for (i = 1; i <= n; i++) {
                    r = parts[i]
                    gsub(/^[ \t]+|[ \t]+$/, "", r)
                    gsub(/^"|"$/, "", r)
                    if (r != "") print r
                }
            }
        ' | sort -u
    }

    if [[ -n "$GLOBALS_FILE" ]]; then
        echo "[restore-db] restoring cluster globals from $GLOBALS_FILE"
        # "role already exists" here is normal and harmless — the roles that do
        # NOT exist are the point. The preflight below re-checks every role the
        # dump references, so anything this misses is still caught.
        if [[ "$GLOBALS_FILE" == *.gz ]]; then
            gunzip -c "$GLOBALS_FILE"
        else
            cat "$GLOBALS_FILE"
        fi | psql_globals 2>&1 | grep -viE '^(SET|CREATE ROLE|ALTER ROLE|GRANT|REVOKE)$|already exists' || true
    else
        echo "[restore-db] no globals file next to the dump — deriving roles from the dump itself"
    fi

    MISSING=()
    while IFS= read -r role; do
        [[ -z "$role" ]] && continue
        case "$role" in
            PUBLIC|public|CURRENT_USER|SESSION_USER|CURRENT_ROLE|pg_*|"$POSTGRES_USER") continue ;;
        esac
        # Captured, not piped into `grep -q`: with `set -o pipefail` that
        # pipeline intermittently reports failure when grep exits early and
        # SIGPIPEs psql, which here would mean re-creating a role that already
        # exists — an ON_ERROR_STOP error that `set -e` turns into an abort.
        exists="$(psql_query -tAc "SELECT 1 FROM pg_roles WHERE rolname = '${role//\'/\'\'}'" 2>/dev/null | tr -d '[:space:]')"
        if [[ "$exists" != "1" ]]; then
            MISSING+=("$role")
        fi
    done < <(dump_roles)

    if (( ${#MISSING[@]} > 0 )); then
        echo "[restore-db] creating ${#MISSING[@]} missing role(s) referenced by the dump: ${MISSING[*]}"
        for role in "${MISSING[@]}"; do
            psql_query -c "CREATE ROLE \"${role//\"/\"\"}\" NOLOGIN"
        done
        echo "[restore-db] WARNING: those roles were created NOLOGIN with no password." >&2
        echo "             Any of them that needs to connect (e.g. grafana_ro for the" >&2
        echo "             metrics exporter, jarvis_mcp when MCP HTTP is enabled) must be" >&2
        echo "             given LOGIN + a password before that client works again." >&2
    else
        echo "[restore-db] role preflight OK — every role the dump references exists"
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
