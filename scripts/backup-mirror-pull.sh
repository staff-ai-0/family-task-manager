#!/usr/bin/env bash
#
# Second copy of the Family Task Manager backups on ANOTHER host.
#
# Runs on the MIRROR host (canonical: 10.1.0.99, user jc, timer
# scripts/systemd/family-backup-mirror.timer), never on the app host. It PULLS
# backups/scheduled/ from the app host (10.1.0.91) over rsync+ssh with a key
# that the app host restricts to read-only rsync of that one directory
# (rrsync -ro, see scripts/systemd/README.md). The direction matters: the app
# host holds no credential for this copy, so a compromised app host can
# neither read, alter nor erase it.
#
# Three properties, all deliberate:
#   - never overwrites a file the mirror already has (--ignore-existing):
#     backups are immutable once written, so a changed file upstream is
#     damage, not an update;
#   - never deletes on sync (no --delete): retention is this script's own
#     prune by age, not whatever happened upstream;
#   - fails loudly (exit 1, so the unit shows failed) when the newest dump it
#     holds is older than MAX_AGE_HOURS — a mirror that silently stopped
#     pulling is the failure that matters, and it would otherwise look green.
#
# Env overrides:
#   MIRROR_SRC        rsync source. With rrsync the remote path is RELATIVE to
#                     the restricted directory, so "host:/" means exactly
#                     backups/scheduled/ — not the remote root. A local path
#                     also works (tests).  Default: jc@10.1.0.91:/
#   MIRROR_DEST       local directory. Default /mnt/nvme/backups/family-task-manager/scheduled
#   MIRROR_SSH_KEY    key for the rsync ssh. Default ~/.ssh/id_ed25519_family_mirror
#   RETENTION_DAYS    prune age on the mirror, default 30 (same as the app host)
#   MAX_AGE_HOURS     newest db dump must be younger than this, default 13
#                     (the app host dumps every 12h; this runs 30 min later)
#
set -euo pipefail

MIRROR_SRC="${MIRROR_SRC:-jc@10.1.0.91:/}"
MIRROR_DEST="${MIRROR_DEST:-/mnt/nvme/backups/family-task-manager/scheduled}"
MIRROR_SSH_KEY="${MIRROR_SSH_KEY:-$HOME/.ssh/id_ed25519_family_mirror}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
MAX_AGE_HOURS="${MAX_AGE_HOURS:-13}"

for v in RETENTION_DAYS MAX_AGE_HOURS; do
    if ! [[ "${!v}" =~ ^[0-9]+$ ]]; then
        echo "[backup-mirror] ERROR: $v must be a whole number, got '${!v}'" >&2
        exit 1
    fi
done

mkdir -p "$MIRROR_DEST"

# ── 1. Pull ─────────────────────────────────────────────────────────────────
# --partial-dir keeps an interrupted transfer out of the way: with
# --ignore-existing a half-written file under its final name would never be
# completed, because the next run would see it as "already there".
RSYNC_ARGS=(-a --ignore-existing --partial-dir=.rsync-partial --timeout=600
            --include='db-*.sql.gz' --include='globals-*.sql.gz' --include='uploads-*.tar.gz'
            --exclude='*')
if [[ "$MIRROR_SRC" == *:* ]]; then
    RSYNC_ARGS+=(-e "ssh -i ${MIRROR_SSH_KEY} -o BatchMode=yes -o ConnectTimeout=15")
fi
echo "[backup-mirror] pulling ${MIRROR_SRC} -> ${MIRROR_DEST}"
if ! rsync "${RSYNC_ARGS[@]}" "${MIRROR_SRC%/}/" "${MIRROR_DEST}/"; then
    echo "[backup-mirror] ERROR: rsync from ${MIRROR_SRC} FAILED — mirror NOT updated" >&2
    exit 1
fi

# ── 2. Freshness ────────────────────────────────────────────────────────────
# rsync -a keeps the upstream mtime, so "newest dump younger than N hours"
# means the app host produced one recently AND this pull fetched it.
NEWEST="$(find "$MIRROR_DEST" -maxdepth 1 -name 'db-*.sql.gz' -type f -mmin "-$((MAX_AGE_HOURS * 60))" | sort | tail -1)"
if [[ -z "$NEWEST" ]]; then
    echo "[backup-mirror] ERROR: no db dump younger than ${MAX_AGE_HOURS}h in ${MIRROR_DEST} — upstream backups stopped or the pull is not fetching" >&2
    exit 1
fi

# ── 3. Prune by age (the mirror's own retention) ────────────────────────────
find "$MIRROR_DEST" -maxdepth 1 \( -name 'db-*.sql.gz' -o -name 'globals-*.sql.gz' -o -name 'uploads-*.tar.gz' \) \
    -type f -mtime "+${RETENTION_DAYS}" -print -delete

echo "[backup-mirror] OK newest=$(basename "$NEWEST") $(find "$MIRROR_DEST" -maxdepth 1 -name 'db-*.sql.gz' | wc -l | tr -d ' ') dumps, $(find "$MIRROR_DEST" -maxdepth 1 -name 'uploads-*.tar.gz' | wc -l | tr -d ' ') uploads archives, $(du -sh "$MIRROR_DEST" | cut -f1)"
