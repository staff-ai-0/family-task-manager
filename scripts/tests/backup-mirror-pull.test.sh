#!/usr/bin/env bash
#
# Regression test for scripts/backup-mirror-pull.sh, run against a local
# source directory (no ssh), so it works on a laptop and in CI:
#
#   bash scripts/tests/backup-mirror-pull.test.sh
#
# Each case is one way the mirror could quietly stop being a backup.
#
set -euo pipefail

SCRIPT="$(cd "$(dirname "$0")/.." && pwd)/backup-mirror-pull.sh"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

FAILED=0
CASE=""

age() {  # age <file> <days> — set mtime N days back
    python3 - "$1" "$2" <<'AGE'
import os, sys, time
t = time.time() - float(sys.argv[2]) * 86400
os.utime(sys.argv[1], (t, t))
AGE
}

new_case() {
    CASE="$1"
    SRC="$WORK/src-$RANDOM$RANDOM"; DEST="$WORK/dest-$RANDOM$RANDOM"
    mkdir -p "$SRC"
    echo "dump-1" > "$SRC/db-20260101-000000.sql.gz"
    echo "roles"  > "$SRC/globals-20260101-000000.sql.gz"
    echo "tar"    > "$SRC/uploads-20260101-000000.tar.gz"
    echo "state"  > "$SRC/.uploads-last-archived"
}

run_mirror() {  # run_mirror [VAR=value ...] — returns the exit code, never aborts
    env MIRROR_SRC="$SRC" MIRROR_DEST="$DEST" "$@" bash "$SCRIPT" > "$WORK/out.log" 2>&1
}

expect() {  # expect <description> <actual> <wanted>
    if [[ "$2" == "$3" ]]; then
        echo "  ok    $CASE: $1"
    else
        echo "  FAIL  $CASE: $1 (got '$2', wanted '$3')"
        sed 's/^/        | /' "$WORK/out.log"
        FAILED=1
    fi
}

# ── 1. Pulls the three artifact kinds and nothing else ──────────────────────
new_case "pull"
run_mirror; expect "exits 0" "$?" 0
expect "copies the dump" "$(cat "$DEST/db-20260101-000000.sql.gz")" dump-1
expect "copies globals + uploads" "$(ls "$DEST" | grep -c 'globals-\|uploads-')" 2
expect "ignores the state file" "$([[ -e "$DEST/.uploads-last-archived" ]] && echo copied || echo skipped)" skipped

# ── 2. Never overwrites a file the mirror already holds ─────────────────────
new_case "immutable"
run_mirror
echo "tampered" > "$SRC/db-20260101-000000.sql.gz"
run_mirror; expect "exits 0" "$?" 0
expect "existing mirror copy untouched" "$(cat "$DEST/db-20260101-000000.sql.gz")" dump-1

# ── 3. Never deletes on sync ────────────────────────────────────────────────
new_case "no delete on sync"
run_mirror
rm "$SRC/uploads-20260101-000000.tar.gz"
run_mirror
expect "file removed upstream stays on the mirror" "$([[ -f "$DEST/uploads-20260101-000000.tar.gz" ]] && echo kept || echo gone)" kept

# ── 4. Fails when the newest dump is stale ──────────────────────────────────
new_case "stale"
age "$SRC/db-20260101-000000.sql.gz" 1
rc=0; run_mirror || rc=$?
expect "a 24h-old newest dump fails the run" "$rc" 1
rc=0; run_mirror MAX_AGE_HOURS=48 || rc=$?
expect "…unless MAX_AGE_HOURS allows it" "$rc" 0

# ── 5. Prunes by age with its own retention ─────────────────────────────────
new_case "prune"
echo "old" > "$SRC/db-20000101-000000.sql.gz";  age "$SRC/db-20000101-000000.sql.gz" 32
echo "mid" > "$SRC/db-20000102-000000.sql.gz";  age "$SRC/db-20000102-000000.sql.gz" 20
run_mirror; expect "exits 0" "$?" 0
expect "32-day-old copy pruned" "$([[ -f "$DEST/db-20000101-000000.sql.gz" ]] && echo kept || echo pruned)" pruned
expect "20-day-old copy kept" "$([[ -f "$DEST/db-20000102-000000.sql.gz" ]] && echo kept || echo pruned)" kept

# ── 6. A failed pull is a failed run ────────────────────────────────────────
new_case "pull failure"
SRC="$WORK/does-not-exist"
rc=0; run_mirror || rc=$?
expect "unreachable source exits 1" "$rc" 1

if [[ "$FAILED" == "0" ]]; then
    echo "PASS"
else
    echo "FAILED"
    exit 1
fi
