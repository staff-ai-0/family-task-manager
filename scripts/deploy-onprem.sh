#!/bin/bash
# ================================
# Family Task Manager — on-prem (10.1.0.91) deploy, rootless podman.
# Transport: rsync + ssh (LAN). NEVER sudo podman (Rule 1).
# ================================
set -e
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
[[ -f "$PROJECT_ROOT/.deploy.onprem.env" ]] && source "$PROJECT_ROOT/.deploy.onprem.env"

REMOTE_HOST="${REMOTE_HOST:-10.1.0.91}"
REMOTE_USER="${REMOTE_USER:-jc}"
REMOTE_PATH="${REMOTE_PATH:-/home/jc/family-task-manager}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.onprem.yml}"
COMPOSE_PROJECT="${COMPOSE_PROJECT:-family-task-manager}"
SSH_TARGET="$REMOTE_USER@$REMOTE_HOST"
DC="podman compose -p $COMPOSE_PROJECT --env-file .env -f $COMPOSE_FILE"

SKIP_CONFIRMATION=false; SKIP_BACKUP=false; SKIP_MIGRATIONS=false; SKIP_BUILD=false
while [[ $# -gt 0 ]]; do case $1 in
  -y|--yes) SKIP_CONFIRMATION=true;; --skip-backup) SKIP_BACKUP=true;;
  --skip-migrations) SKIP_MIGRATIONS=true;; --skip-build) SKIP_BUILD=true;;
  *) echo "unknown option: $1"; exit 1;; esac; shift; done

rssh() { ssh -o BatchMode=yes "$SSH_TARGET" "$1"; }
section() { echo; echo "━━━ $* ━━━"; }

# ── Pre-flight ────────────────────────────────────────────────────────────
section "Pre-flight"
[[ -f "$PROJECT_ROOT/$COMPOSE_FILE" ]] || { echo "missing $COMPOSE_FILE"; exit 1; }
rssh 'podman info >/dev/null' || { echo "rootless podman not available for $SSH_TARGET"; exit 1; }
rssh "podman info --format '{{.Store.GraphRoot}}'" | grep -qv '/var/lib/containers' \
  || { echo "REFUSING: podman GraphRoot looks like system storage — check you are rootless jc"; exit 1; }
echo "rootless podman OK on $REMOTE_HOST"

if [[ "$SKIP_CONFIRMATION" != "true" ]]; then
  echo "Deploy to $SSH_TARGET:$REMOTE_PATH ($COMPOSE_FILE)?"
  read -r -p "Type 'DEPLOY' to continue: " R; [[ "$R" == "DEPLOY" ]] || exit 0
fi

# ── Backup (if stack already running) ─────────────────────────────────────
if [[ "$SKIP_BACKUP" != "true" ]]; then
  section "Backup"
  # shellcheck disable=SC2086
  rssh "cd $REMOTE_PATH && if $DC ps postgres 2>/dev/null | grep -q Up; then \
    COMPOSE_CMD='podman compose' COMPOSE_FILE=$COMPOSE_FILE ./scripts/backup-db.sh; \
    else echo 'no running postgres — skipping'; fi"
fi

# ── Sync code ─────────────────────────────────────────────────────────────
section "Sync"
rssh "mkdir -p $REMOTE_PATH"
rsync -avz --delete \
  --exclude='.git/' --exclude='node_modules/' --exclude='__pycache__/' \
  --exclude='*.pyc' --exclude='.venv/' --exclude='venv/' --exclude='dist/' \
  --exclude='.astro/' --exclude='logs/' --exclude='backups/' --exclude='htmlcov/' \
  --exclude='playwright-report/' --exclude='test-results/' --exclude='e2e-tests/' \
  --exclude='.env' --exclude='.env.local' --exclude='.deploy.onprem.env' \
  -e "ssh -o BatchMode=yes" \
  "$PROJECT_ROOT/" "$SSH_TARGET:$REMOTE_PATH/"

# ── Guard: .env must exist ────────────────────────────────────────────────
rssh "[[ -f $REMOTE_PATH/.env ]]" || { echo "❌ .env missing on host — cp .env.onprem.example .env and fill secrets"; exit 1; }

# ── Build ─────────────────────────────────────────────────────────────────
if [[ "$SKIP_BUILD" != "true" ]]; then
  section "Build"
  # shellcheck disable=SC2086
  rssh "cd $REMOTE_PATH && $DC build backend frontend"
fi

# ── Prepare volumes (rootless UID mapping — Rule 4) ───────────────────────
section "Prepare volumes"
rssh "cd $REMOTE_PATH && \
  podman volume create ${COMPOSE_PROJECT}_postgres_data >/dev/null 2>&1 || true; \
  podman volume create ${COMPOSE_PROJECT}_redis_data >/dev/null 2>&1 || true; \
  podman volume create ${COMPOSE_PROJECT}_receipt_uploads >/dev/null 2>&1 || true; \
  podman unshare chown -R 70:70   \$(podman volume inspect ${COMPOSE_PROJECT}_postgres_data --format '{{.Mountpoint}}'); \
  podman unshare chown -R 999:1000 \$(podman volume inspect ${COMPOSE_PROJECT}_redis_data --format '{{.Mountpoint}}'); \
  podman unshare chown -R 1000:1000 \$(podman volume inspect ${COMPOSE_PROJECT}_receipt_uploads --format '{{.Mountpoint}}')"

# ── Migrate against new image (old backend keeps serving) ─────────────────
if [[ "$SKIP_MIGRATIONS" != "true" ]]; then
  section "Migrate"
  # shellcheck disable=SC2086
  rssh "cd $REMOTE_PATH && $DC up -d --no-recreate postgres redis"
  # wait postgres healthy
  rssh "cd $REMOTE_PATH && for i in \$(seq 1 30); do \
    [ \"\$(podman inspect --format '{{.State.Health.Status}}' family_onprem_db 2>/dev/null)\" = healthy ] && break; sleep 2; done"
  # shellcheck disable=SC2086
  rssh "cd $REMOTE_PATH && $DC run --rm -T --no-deps backend alembic upgrade head"
  # shellcheck disable=SC2086
  rssh "cd $REMOTE_PATH && $DC run --rm -T --no-deps backend alembic current"
fi

# ── Start ─────────────────────────────────────────────────────────────────
section "Start"
# shellcheck disable=SC2086
rssh "cd $REMOTE_PATH && $DC up -d"

section "Health"
for c in family_onprem_db family_onprem_redis family_onprem_backend family_onprem_frontend; do
  rssh "for i in \$(seq 1 40); do \
    s=\$(podman inspect --format '{{.State.Health.Status}}' $c 2>/dev/null); \
    [ \"\$s\" = healthy ] && { echo '$c healthy'; break; }; sleep 3; done; \
    [ \"\$(podman inspect --format '{{.State.Health.Status}}' $c 2>/dev/null)\" = healthy ] || echo '⚠️ $c not healthy'"
done
# shellcheck disable=SC2086
rssh "cd $REMOTE_PATH && $DC ps"

# ── Verify public (may 000 until tunnel + DNS live) ───────────────────────
section "Verify public"
for url in https://family.agent-ia.mx https://api-family.agent-ia.mx/health; do
  code=$(curl -s -o /dev/null -w '%{http_code}' "$url" 2>/dev/null || echo 000)
  echo "$url → $code"
done
echo "Deploy complete."
