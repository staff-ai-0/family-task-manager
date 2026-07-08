#!/bin/bash
# ================================
# Family Task Manager — on-prem (10.1.0.91) deploy, rootless podman.
# Transport: rsync + ssh (LAN). NEVER sudo podman (Rule 1).
#
# Flow: backup → rsync → snapshot rollback point → build → tag both images
# with the git short SHA → record PREV_TAG/NEW_TAG (+ repos) in
# $REMOTE_PATH/.deploy-state → alembic migrate against the NEW image (old
# backend keeps serving) → recreate the pod (scoped `down` + re-pin egress
# DNS + `up` — a plain `up -d` does NOT swap pod containers onto a rebuilt
# image) → health-check → public smoke.
#
# Rollback:
#   * AUTOMATIC — if the post-up health check fails, the PREV_TAG images are
#     retagged as the compose tag, the pod is recreated again and health is
#     re-checked; a ROLLED BACK banner is printed and the script exits
#     non-zero either way. NOTE: alembic has ALREADY run at that point — the
#     DB schema may be AHEAD of the rolled-back code. This script never
#     auto-downgrades the DB; manual follow-ups are scripts/restore-db.sh
#     (pre-deploy dump in $REMOTE_PATH/backups/) or an explicit
#     `alembic downgrade` of the new migration(s).
#   * MANUAL — ./scripts/deploy-onprem.sh --rollback [-y]
#     retags PREV_TAG from $REMOTE_PATH/.deploy-state and recreates the pod.
#     No rsync/build/migrate/backup. Same DB-schema caveat applies.
#
# Dry run (print remote commands instead of executing; no ssh/rsync/curl):
#   DEPLOY_DRY_RUN=1 ./scripts/deploy-onprem.sh -y [--rollback]
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
STATE_FILE="$REMOTE_PATH/.deploy-state"
DRY_RUN="${DEPLOY_DRY_RUN:-0}"

SKIP_CONFIRMATION=false; SKIP_BACKUP=false; SKIP_MIGRATIONS=false; SKIP_BUILD=false; ROLLBACK=false
while [[ $# -gt 0 ]]; do case $1 in
  -y|--yes) SKIP_CONFIRMATION=true;; --skip-backup) SKIP_BACKUP=true;;
  --skip-migrations) SKIP_MIGRATIONS=true;; --skip-build) SKIP_BUILD=true;;
  --rollback) ROLLBACK=true;;
  *) echo "unknown option: $1 (known: -y --skip-backup --skip-migrations --skip-build --rollback)"; exit 1;; esac; shift; done

rssh() {
  if [[ "$DRY_RUN" == "1" ]]; then echo "[dry-run] ssh $SSH_TARGET: $1" >&2; return 0; fi
  ssh -o BatchMode=yes "$SSH_TARGET" "$1"
}
section() { echo; echo "━━━ $* ━━━"; }

# Image repos + tags. BACKEND_REPO/FRONTEND_REPO/COMPOSE_TAG are detected from
# the running containers (whatever naming the compose provider used) but can
# be overridden in .deploy.onprem.env.
BACKEND_REPO="${BACKEND_REPO:-}"; FRONTEND_REPO="${FRONTEND_REPO:-}"
COMPOSE_TAG="${COMPOSE_TAG:-}"; PREV_TAG=""; NEW_TAG=""; STATE_CONTENT=""

image_ref_of() { # container name → its image ref (e.g. localhost/proj_backend:latest), empty if absent
  rssh "podman inspect --format '{{.ImageName}}' $1 2>/dev/null" 2>/dev/null || true
}

sget() { # read KEY from $STATE_CONTENT (host .deploy-state)
  sed -n "s/^$1=//p" <<<"$STATE_CONTENT" | head -1
}

write_state() { # $1=prev tag, $2=new tag — record the rollback point on the host
  rssh "printf '%s\n' \
    'PREV_TAG=$1' \
    'NEW_TAG=$2' \
    'BACKEND_REPO=$BACKEND_REPO' \
    'FRONTEND_REPO=$FRONTEND_REPO' \
    'COMPOSE_TAG=$COMPOSE_TAG' \
    'UPDATED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)' \
    > $STATE_FILE"
}

# ── Pod recreate (scoped down + re-pin + up) ──────────────────────────────
# The stack runs as a podman POD. `podman compose up -d` alone does NOT swap
# pod containers onto a freshly-built image — it treats the existing
# containers as up-to-date, so a rebuild silently keeps serving the OLD image
# while the deploy still reports healthy + 200. Recreate the pod: `down`,
# re-pin the egress DNS (down removes the project networks), then `up`.
# Brief downtime (~1 min) is the trade for actually shipping the new image.
# DO NOT "simplify" this back to a bare `up -d`.
recreate_stack() {
  rssh "cd $REMOTE_PATH && $DC down"
  rssh "podman network exists ${COMPOSE_PROJECT}_frontend || \
    podman network create --dns 1.1.1.1 --dns 8.8.8.8 ${COMPOSE_PROJECT}_frontend"
  rssh "podman network inspect ${COMPOSE_PROJECT}_frontend --format '{{.NetworkDNSServers}}' | grep -q 1.1.1.1 || \
    podman network update ${COMPOSE_PROJECT}_frontend --dns-add 1.1.1.1 --dns-add 8.8.8.8"
  rssh "podman network exists ${COMPOSE_PROJECT}_backend || \
    podman network create --internal ${COMPOSE_PROJECT}_backend"
  rssh "cd $REMOTE_PATH && $DC up -d"
}

wait_healthy() { # poll all containers to healthy; returns non-zero if any fail
  local fail=0 c
  for c in family_onprem_db family_onprem_redis family_onprem_backend family_onprem_frontend; do
    if ! rssh "for i in \$(seq 1 40); do \
      s=\$(podman inspect --format '{{.State.Health.Status}}' $c 2>/dev/null); \
      [ \"\$s\" = healthy ] && { echo '$c healthy'; break; }; sleep 3; done; \
      [ \"\$(podman inspect --format '{{.State.Health.Status}}' $c 2>/dev/null)\" = healthy ]"; then
      echo "⚠️ $c not healthy"; fail=1
    fi
  done
  rssh "cd $REMOTE_PATH && $DC ps"
  return $fail
}

rollback_to_prev() { # retag :$PREV_TAG as the compose tag, then recreate the pod
  rssh "podman tag $BACKEND_REPO:$PREV_TAG $BACKEND_REPO:$COMPOSE_TAG"
  rssh "podman tag $FRONTEND_REPO:$PREV_TAG $FRONTEND_REPO:$COMPOSE_TAG"
  recreate_stack
}

db_schema_warning() {
  cat <<EOF

!! ═══════════════════════════════════════════════════════════════════ !!
!!  DB SCHEMA WARNING — alembic migrations have ALREADY RUN against
!!  the NEW code. Rolling back containers does NOT roll back the
!!  database: the schema may now be AHEAD of the rolled-back code.
!!
!!  If the old code errors against the new schema, follow up by hand:
!!    1. Restore the pre-deploy dump taken by this script's Backup step
!!       (host: $REMOTE_PATH/backups/) via scripts/restore-db.sh
!!    2. Or downgrade just the new migration(s) on the host:
!!       $DC run --rm -T --no-deps backend alembic downgrade <prev-rev>
!!
!!  This script NEVER auto-downgrades the DB.
!! ═══════════════════════════════════════════════════════════════════ !!

EOF
}

verify_public() {
  section "Verify public"
  if [[ "$DRY_RUN" == "1" ]]; then echo "[dry-run] skipping public endpoint checks"; return 0; fi
  local url code
  for url in https://family.agent-ia.mx https://api-family.agent-ia.mx/health; do
    code=$(curl -s -o /dev/null -w '%{http_code}' "$url" 2>/dev/null || echo 000)
    echo "$url → $code"
  done
}

# ── Pre-flight ────────────────────────────────────────────────────────────
section "Pre-flight"
[[ -f "$PROJECT_ROOT/$COMPOSE_FILE" ]] || { echo "missing $COMPOSE_FILE"; exit 1; }
if [[ "$DRY_RUN" == "1" ]]; then
  echo "[dry-run] skipping remote pre-flight checks"
else
  rssh 'podman info >/dev/null' || { echo "rootless podman not available for $SSH_TARGET"; exit 1; }
  rssh "podman info --format '{{.Store.GraphRoot}}'" | grep -qv '/var/lib/containers' \
    || { echo "REFUSING: podman GraphRoot looks like system storage — check you are rootless jc"; exit 1; }
  echo "rootless podman OK on $REMOTE_HOST"
fi

# ── Manual rollback (--rollback): retag PREV_TAG + recreate, nothing else ──
if [[ "$ROLLBACK" == "true" ]]; then
  section "Manual rollback"
  STATE_CONTENT="$(rssh "cat $STATE_FILE 2>/dev/null" 2>/dev/null || true)"
  if [[ -z "$STATE_CONTENT" && "$DRY_RUN" == "1" ]]; then
    STATE_CONTENT="PREV_TAG=dryrun-prev
NEW_TAG=dryrun-new
BACKEND_REPO=localhost/${COMPOSE_PROJECT}_backend
FRONTEND_REPO=localhost/${COMPOSE_PROJECT}_frontend
COMPOSE_TAG=latest"
    echo "[dry-run] using placeholder state (no $STATE_FILE read)"
  fi
  PREV_TAG="$(sget PREV_TAG)"; NEW_TAG="$(sget NEW_TAG)"
  BACKEND_REPO="${BACKEND_REPO:-$(sget BACKEND_REPO)}"
  FRONTEND_REPO="${FRONTEND_REPO:-$(sget FRONTEND_REPO)}"
  COMPOSE_TAG="${COMPOSE_TAG:-$(sget COMPOSE_TAG)}"; COMPOSE_TAG="${COMPOSE_TAG:-latest}"
  if [[ -z "$PREV_TAG" || -z "$BACKEND_REPO" || -z "$FRONTEND_REPO" ]]; then
    echo "❌ $STATE_FILE missing or incomplete on $SSH_TARGET — nothing to roll back to."
    echo "   (The state file is written by each deploy; run a full deploy first.)"
    exit 1
  fi
  echo "Roll back $SSH_TARGET to image tag ':$PREV_TAG' (state says current is ':$NEW_TAG')."
  echo "  backend:  $BACKEND_REPO:$PREV_TAG → :$COMPOSE_TAG"
  echo "  frontend: $FRONTEND_REPO:$PREV_TAG → :$COMPOSE_TAG"
  db_schema_warning
  if [[ "$SKIP_CONFIRMATION" != "true" ]]; then
    read -r -p "Type 'ROLLBACK' to continue: " R; [[ "$R" == "ROLLBACK" ]] || exit 0
  fi
  rssh "podman image exists $BACKEND_REPO:$PREV_TAG && podman image exists $FRONTEND_REPO:$PREV_TAG" \
    || { echo "❌ image tag :$PREV_TAG not found on host for both repos — cannot roll back"; exit 1; }
  rollback_to_prev || true
  section "Health"
  if wait_healthy; then
    write_state "$PREV_TAG" "$PREV_TAG"
    verify_public
    echo
    echo "════════════════════════════════════════════════════════════════"
    echo "  ROLLED BACK — stack is healthy on image tag :$PREV_TAG."
    echo "  Remember the DB-schema warning above if migrations had run."
    echo "════════════════════════════════════════════════════════════════"
    exit 0
  else
    echo
    echo "════════════════════════════════════════════════════════════════"
    echo "  ROLLBACK FAILED — stack UNHEALTHY after retag to :$PREV_TAG."
    echo "  Manual intervention required on $SSH_TARGET (podman ps / logs)."
    echo "════════════════════════════════════════════════════════════════"
    exit 1
  fi
fi

if [[ "$SKIP_CONFIRMATION" != "true" ]]; then
  echo "Deploy to $SSH_TARGET:$REMOTE_PATH ($COMPOSE_FILE)?"
  read -r -p "Type 'DEPLOY' to continue: " R; [[ "$R" == "DEPLOY" ]] || exit 0
fi

# ── Backup (if stack already running) ─────────────────────────────────────
if [[ "$SKIP_BACKUP" != "true" ]]; then
  section "Backup"
  rssh "cd $REMOTE_PATH && if [ \"\$(podman inspect --format '{{.State.Running}}' family_onprem_db 2>/dev/null)\" = true ]; then \
    COMPOSE_CMD='podman compose' COMPOSE_FILE=$COMPOSE_FILE ./scripts/backup-db.sh; \
    else echo 'no running postgres — skipping backup'; fi"
fi

# ── Sync code ─────────────────────────────────────────────────────────────
section "Sync"
rssh "mkdir -p $REMOTE_PATH"
if [[ "$DRY_RUN" == "1" ]]; then
  echo "[dry-run] rsync $PROJECT_ROOT/ → $SSH_TARGET:$REMOTE_PATH/ (skipped)"
else
  rsync -avz --delete \
    --exclude='.git/' --exclude='node_modules/' --exclude='__pycache__/' \
    --exclude='*.pyc' --exclude='.venv/' --exclude='venv/' --exclude='dist/' \
    --exclude='.astro/' --exclude='logs/' --exclude='backups/' --exclude='htmlcov/' \
    --exclude='playwright-report/' --exclude='test-results/' --exclude='e2e-tests/' \
    --exclude='.env' --exclude='.env.local' --exclude='.deploy.onprem.env' \
    --exclude='.deploy-state' \
    -e "ssh -o BatchMode=yes" \
    "$PROJECT_ROOT/" "$SSH_TARGET:$REMOTE_PATH/"
fi

# ── Guard: .env must exist ────────────────────────────────────────────────
rssh "[[ -f $REMOTE_PATH/.env ]]" || { echo "❌ .env missing on host — cp .env.onprem.example .env and fill secrets"; exit 1; }

# ── Rollback point (preserve the currently-running images BEFORE rebuild) ─
section "Rollback point"
NEW_TAG="$(git -C "$PROJECT_ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"
git -C "$PROJECT_ROOT" diff --quiet 2>/dev/null || NEW_TAG="${NEW_TAG}-dirty"

bref="$(image_ref_of family_onprem_backend)"
fref="$(image_ref_of family_onprem_frontend)"
[[ -n "$BACKEND_REPO"  ]] || { [[ "$bref" == *:* ]] && BACKEND_REPO="${bref%:*}"; } || true
[[ -n "$FRONTEND_REPO" ]] || { [[ "$fref" == *:* ]] && FRONTEND_REPO="${fref%:*}"; } || true
[[ -n "$COMPOSE_TAG"   ]] || { [[ "$bref" == *:* ]] && COMPOSE_TAG="${bref##*:}"; } || true
COMPOSE_TAG="${COMPOSE_TAG:-latest}"
if [[ "$DRY_RUN" == "1" ]]; then
  BACKEND_REPO="${BACKEND_REPO:-localhost/${COMPOSE_PROJECT}_backend}"
  FRONTEND_REPO="${FRONTEND_REPO:-localhost/${COMPOSE_PROJECT}_frontend}"
fi

if [[ -n "$BACKEND_REPO" && -n "$FRONTEND_REPO" ]]; then
  STATE_CONTENT="$(rssh "cat $STATE_FILE 2>/dev/null" 2>/dev/null || true)"
  last_tag="$(sget NEW_TAG)"
  if [[ -n "$last_tag" && "$last_tag" != "$NEW_TAG" ]] && \
     rssh "podman image exists $BACKEND_REPO:$last_tag && podman image exists $FRONTEND_REPO:$last_tag" 2>/dev/null; then
    # previous deploy's SHA tag still exists on the host — that's our rollback point
    PREV_TAG="$last_tag"
  elif rssh "podman inspect --format '{{.Image}}' family_onprem_backend family_onprem_frontend >/dev/null 2>&1" 2>/dev/null; then
    # no usable prior SHA tag — snapshot the currently-running images so the
    # rebuild (which reassigns :$COMPOSE_TAG) can't orphan them
    PREV_TAG="pre-$(date +%Y%m%d-%H%M%S)"
    rssh "podman tag \$(podman inspect --format '{{.Image}}' family_onprem_backend)  $BACKEND_REPO:$PREV_TAG"
    rssh "podman tag \$(podman inspect --format '{{.Image}}' family_onprem_frontend) $FRONTEND_REPO:$PREV_TAG"
  fi
fi
if [[ -n "$PREV_TAG" ]]; then
  echo "rollback point: :$PREV_TAG ($BACKEND_REPO, $FRONTEND_REPO)"
else
  echo "⚠️ no rollback point (stack not running / first deploy?) — automatic rollback DISABLED for this run"
fi

# ── Build ─────────────────────────────────────────────────────────────────
if [[ "$SKIP_BUILD" != "true" ]]; then
  section "Build"
  rssh "cd $REMOTE_PATH && $DC build backend frontend"
fi

# ── Tag new images with the git SHA + record state ────────────────────────
section "Tag images (:$NEW_TAG)"
if [[ -z "$BACKEND_REPO" || -z "$FRONTEND_REPO" ]]; then
  # cold start (no containers pre-build): find the freshly built images by
  # the two compose-provider naming conventions
  for cand in "localhost/${COMPOSE_PROJECT}_backend" "localhost/${COMPOSE_PROJECT}-backend"; do
    rssh "podman image exists $cand:$COMPOSE_TAG" 2>/dev/null && { BACKEND_REPO="$cand"; break; } || true
  done
  for cand in "localhost/${COMPOSE_PROJECT}_frontend" "localhost/${COMPOSE_PROJECT}-frontend"; do
    rssh "podman image exists $cand:$COMPOSE_TAG" 2>/dev/null && { FRONTEND_REPO="$cand"; break; } || true
  done
fi
if [[ -n "$BACKEND_REPO" && -n "$FRONTEND_REPO" ]]; then
  rssh "podman tag $BACKEND_REPO:$COMPOSE_TAG $BACKEND_REPO:$NEW_TAG"
  rssh "podman tag $FRONTEND_REPO:$COMPOSE_TAG $FRONTEND_REPO:$NEW_TAG"
  write_state "$PREV_TAG" "$NEW_TAG"
  echo "tagged :$NEW_TAG; state → $STATE_FILE (PREV_TAG=${PREV_TAG:-<none>} NEW_TAG=$NEW_TAG)"
else
  echo "⚠️ could not determine compose image names — SHA tagging + rollback unavailable this run"
fi

# ── Prepare networks (rootless netavark external-DNS pin) ─────────────────
# The host resolv.conf's IPv6 link-local upstream (fe80::1%eno1) breaks
# aardvark external forwarding, so cloudflared can't reach the Cloudflare edge
# (HTTP 530) and the backend can't resolve LiteLLM/OAuth/PayPal/SMTP. Pin
# explicit DNS on the egress network. Pre-create both nets before any `up` so
# containers start with working resolution (matches the sibling stacks on .91).
section "Prepare networks"
rssh "podman network exists ${COMPOSE_PROJECT}_frontend || \
  podman network create --dns 1.1.1.1 --dns 8.8.8.8 ${COMPOSE_PROJECT}_frontend"
rssh "podman network inspect ${COMPOSE_PROJECT}_frontend --format '{{.NetworkDNSServers}}' | grep -q 1.1.1.1 || \
  podman network update ${COMPOSE_PROJECT}_frontend --dns-add 1.1.1.1 --dns-add 8.8.8.8"
rssh "podman network exists ${COMPOSE_PROJECT}_backend || \
  podman network create --internal ${COMPOSE_PROJECT}_backend"

# ── Prepare volumes (rootless UID mapping — Rule 4) ───────────────────────
section "Prepare volumes"
rssh "cd $REMOTE_PATH && \
  { podman volume create ${COMPOSE_PROJECT}_postgres_data >/dev/null 2>&1 || true; } && \
  { podman volume create ${COMPOSE_PROJECT}_redis_data >/dev/null 2>&1 || true; } && \
  { podman volume create ${COMPOSE_PROJECT}_receipt_uploads >/dev/null 2>&1 || true; } && \
  podman unshare chown -R 70:70   \$(podman volume inspect ${COMPOSE_PROJECT}_postgres_data --format '{{.Mountpoint}}') && \
  podman unshare chown -R 999:1000 \$(podman volume inspect ${COMPOSE_PROJECT}_redis_data --format '{{.Mountpoint}}') && \
  podman unshare chown -R 1000:1000 \$(podman volume inspect ${COMPOSE_PROJECT}_receipt_uploads --format '{{.Mountpoint}}')"

# ── Migrate against new image (old backend keeps serving) ─────────────────
if [[ "$SKIP_MIGRATIONS" != "true" ]]; then
  section "Migrate"
  rssh "cd $REMOTE_PATH && $DC up -d --no-recreate postgres redis"
  # wait postgres healthy
  rssh "cd $REMOTE_PATH && for i in \$(seq 1 30); do \
    [ \"\$(podman inspect --format '{{.State.Health.Status}}' family_onprem_db 2>/dev/null)\" = healthy ] && break; sleep 2; done; \
    [ \"\$(podman inspect --format '{{.State.Health.Status}}' family_onprem_db 2>/dev/null)\" = healthy ] || { echo '❌ postgres not healthy after 60s — aborting before migrate'; exit 1; }"
  rssh "cd $REMOTE_PATH && $DC run --rm -T --no-deps backend alembic upgrade head"
  rssh "cd $REMOTE_PATH && $DC run --rm -T --no-deps backend alembic current"
fi

# ── Start (scoped pod recreate — see recreate_stack) ──────────────────────
section "Start"
recreate_stack

section "Health"
if ! wait_healthy; then
  echo "❌ one or more containers unhealthy after deploy — attempting automatic rollback"
  db_schema_warning
  if [[ -z "$PREV_TAG" || -z "$BACKEND_REPO" || -z "$FRONTEND_REPO" ]] || \
     ! rssh "podman image exists $BACKEND_REPO:$PREV_TAG && podman image exists $FRONTEND_REPO:$PREV_TAG" 2>/dev/null; then
    echo
    echo "════════════════════════════════════════════════════════════════"
    echo "  DEPLOY FAILED — NO ROLLBACK POINT available (no previous image"
    echo "  tag). Manual recovery required on $SSH_TARGET:"
    echo "    ssh $SSH_TARGET 'cd $REMOTE_PATH && $DC ps'"
    echo "    ssh $SSH_TARGET 'cd $REMOTE_PATH && $DC logs backend'"
    echo "════════════════════════════════════════════════════════════════"
    exit 1
  fi
  section "Rollback → :$PREV_TAG"
  rollback_to_prev || true
  if wait_healthy; then
    write_state "$PREV_TAG" "$PREV_TAG"
    echo
    echo "════════════════════════════════════════════════════════════════"
    echo "  DEPLOY FAILED — ROLLED BACK to :$PREV_TAG. Stack is healthy on"
    echo "  the PREVIOUS image. Fix forward and redeploy."
    echo "  ⚠️ DB schema may be AHEAD of this code — see warning above"
    echo "  (scripts/restore-db.sh / alembic downgrade are manual)."
    echo "════════════════════════════════════════════════════════════════"
  else
    echo
    echo "════════════════════════════════════════════════════════════════"
    echo "  DEPLOY FAILED — ROLLED BACK to :$PREV_TAG but stack is STILL"
    echo "  UNHEALTHY. Manual intervention required on $SSH_TARGET"
    echo "  (podman ps / $DC logs backend). DB warning above applies."
    echo "════════════════════════════════════════════════════════════════"
  fi
  exit 1
fi

verify_public
echo "Deploy complete. (deployed :$NEW_TAG, rollback point :${PREV_TAG:-<none>} — ./scripts/deploy-onprem.sh --rollback)"
