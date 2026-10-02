#!/usr/bin/env bash
#
# Regression test for the uploads-archive skip logic in scripts/backup-db.sh.
#
# Runs the real script against stubbed `podman`, `gsutil` and compose commands
# (no containers, no network), so it works on a laptop and in CI:
#
#   bash scripts/tests/backup-uploads-skip.test.sh
#
# Why this exists: until 2026-10 every run re-archived the whole uploads
# volume, changed or not — 4-8 identical ~850 MB copies a day, 56 GB on the
# prod disk and 96 GB offsite. The skip must never become "skip forever":
# each case below is one way an unchanged volume could end up with NO
# restorable copy.
#
set -euo pipefail

SCRIPT="$(cd "$(dirname "$0")/.." && pwd)/backup-db.sh"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

mkdir -p "$WORK/bin"

# podman: one receipt_uploads volume whose "export" is the bytes of $FAKE_VOLUME.
cat > "$WORK/bin/podman" <<'STUB'
#!/usr/bin/env bash
case "$1 $2" in
    "volume ls")     echo "app_receipt_uploads" ;;
    "volume export") cat "$FAKE_VOLUME" ;;
    *) echo "podman stub: unexpected: $*" >&2; exit 64 ;;
esac
STUB

# compose: both pg_dump and pg_dumpall just need to emit a CREATE ROLE line.
cat > "$WORK/bin/fakecompose" <<'STUB'
#!/usr/bin/env bash
echo "CREATE ROLE app;"
STUB

# gsutil: log the destination of every push; GSUTIL_FAIL=1 simulates an outage.
cat > "$WORK/bin/gsutil" <<'STUB'
#!/usr/bin/env bash
[[ "${GSUTIL_FAIL:-0}" == "1" ]] && exit 1
echo "${@: -1}" >> "$GSUTIL_LOG"
STUB
chmod +x "$WORK/bin/"*

FAILED=0
CASE=""

# Fresh app dir per case so state never leaks between them.
new_app() {
    CASE="$1"
    APP="$WORK/app-$RANDOM$RANDOM"
    mkdir -p "$APP"
    printf 'POSTGRES_USER=app\nPOSTGRES_DB=app\n' > "$APP/.env"
    : > "$APP/key.json"
    export FAKE_VOLUME="$APP/volume.bin"
    export GSUTIL_LOG="$APP/gsutil.log"
    echo "receipt-1" > "$FAKE_VOLUME"
}

# run_backup [VAR=value ...] — returns the script's exit code, never aborts.
run_backup() {
    : > "$GSUTIL_LOG"
    env PATH="$WORK/bin:$PATH" APP_DIR="$APP" COMPOSE_CMD=fakecompose \
        GCS_KEY_FILE="$APP/key.json" OFFSITE_GCS_BUCKET=gs://test-bucket/scheduled \
        "$@" bash "$SCRIPT" > "$APP/out.log" 2>&1
}

uploads_pushed() { grep -c '/uploads-' "$GSUTIL_LOG" || true; }
db_pushed()      { grep -c '/db-' "$GSUTIL_LOG" || true; }

expect() {  # expect <description> <actual> <wanted>
    if [[ "$2" == "$3" ]]; then
        echo "  ok    $CASE: $1"
    else
        echo "  FAIL  $CASE: $1 (got '$2', wanted '$3')"
        sed 's/^/        | /' "$APP/out.log"
        FAILED=1
    fi
}

last_archive() { cut -d' ' -f2 "$APP/backups/scheduled/.uploads-last-archived"; }

# ── 1. First run archives; an unchanged second run does not ─────────────────
new_app "unchanged volume"
run_backup;  expect "first run exits 0" "$?" 0
expect "first run pushes the uploads archive" "$(uploads_pushed)" 1
run_backup;  expect "second run exits 0" "$?" 0
expect "second run skips the uploads archive" "$(uploads_pushed)" 0
expect "second run still pushes the DB dump" "$(db_pushed)" 1

# ── 2. A changed volume is archived again ───────────────────────────────────
new_app "changed volume"
run_backup
echo "receipt-2" >> "$FAKE_VOLUME"
run_backup
expect "changed content is re-archived" "$(uploads_pushed)" 1

# ── 3. An archive that never reached offsite does not count as done ─────────
new_app "failed push"
rc=0; run_backup GSUTIL_FAIL=1 || rc=$?
expect "failed push exits non-zero" "$rc" 1
run_backup
expect "next run re-archives the unchanged volume" "$(uploads_pushed)" 1

# ── 4. The last archive aged past UPLOADS_MAX_AGE_DAYS is refreshed ─────────
# Otherwise retention (local) and the bucket lifecycle (offsite) would delete
# the only copy of a volume that simply has not changed in a month.
new_app "stale archive"
run_backup
touch -t 202001010000 "$APP/backups/scheduled/$(last_archive)"
run_backup
expect "stale last archive is refreshed" "$(uploads_pushed)" 1

# ── 5. The last archive missing from disk is replaced ───────────────────────
new_app "missing archive"
run_backup
rm "$APP/backups/scheduled/$(last_archive)"
run_backup
expect "missing last archive is replaced" "$(uploads_pushed)" 1

# ── 6. UPLOADS_MAX_AGE_DAYS=0 disables the skip (forced hand-run) ───────────
new_app "max age 0"
run_backup
run_backup UPLOADS_MAX_AGE_DAYS=0
expect "UPLOADS_MAX_AGE_DAYS=0 always archives" "$(uploads_pushed)" 1

# ── 7. A new offsite destination has no copy yet, whatever the old one holds ─
new_app "destination changed"
run_backup
run_backup OFFSITE_GCS_BUCKET=gs://other-bucket/scheduled
expect "new destination gets its own uploads archive" "$(uploads_pushed)" 1

if [[ "$FAILED" == "0" ]]; then
    echo "PASS"
else
    echo "FAILED"
    exit 1
fi
