#!/bin/bash
# ================================
# Family Task Manager — GCP Deployment Script
# ================================
#
# Deploys to a GCP VM in project `urologos`.
# Transport: rsync over `gcloud compute ssh` (no GitHub round-trip required).
#
# Usage:
#   ./scripts/deploy-gcp.sh [OPTIONS]
#
# Configurable via env vars or .deploy.gcp.env:
#   GCP_ACCOUNT     (default: info@agent-ia.mx)
#   GCP_PROJECT     (default: urologos)
#   GCP_ZONE        (default: us-central1-a)
#   GCP_VM          (default: agentia-family-hub)
#   REMOTE_USER     (default: jc)
#   REMOTE_PATH     (default: /home/jc/family-task-manager)
#   COMPOSE_FILE    (default: docker-compose.gcp.yml)
# ================================

set -e
set -o pipefail

# ── Config ────────────────────────────────────────────────────────────────
GCP_ACCOUNT="${GCP_ACCOUNT:-info@agent-ia.mx}"
GCP_PROJECT="${GCP_PROJECT:-urologos}"
GCP_ZONE="${GCP_ZONE:-us-central1-a}"
GCP_VM="${GCP_VM:-agentia-family-hub}"
REMOTE_USER="${REMOTE_USER:-jc}"
REMOTE_PATH="${REMOTE_PATH:-/home/jc/family-task-manager}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.gcp.yml}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$PROJECT_ROOT/logs"
LOG_FILE="$LOG_DIR/deploy-gcp-$(date +%Y%m%d-%H%M%S).log"

# Load optional override file
if [[ -f "$PROJECT_ROOT/.deploy.gcp.env" ]]; then
    # shellcheck disable=SC1091
    source "$PROJECT_ROOT/.deploy.gcp.env"
fi

# ── Options ───────────────────────────────────────────────────────────────
SKIP_CONFIRMATION=false
SKIP_BACKUP=false
SKIP_MIGRATIONS=false
SKIP_BUILD=false
SKIP_SEED=true
SHOW_LOGS=false
LOG_TAIL=50

# ── Colors ────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; MAGENTA='\033[0;35m'; CYAN='\033[0;36m'; NC='\033[0m'

print_color() { local c=$1; shift; echo -e "${c}$*${NC}"; }
error()       { print_color "$RED"     "❌ $*"; }
warning()     { print_color "$YELLOW"  "⚠️  $*"; }
success()     { print_color "$GREEN"   "✅ $*"; }
info()        { print_color "$CYAN"    "ℹ️  $*"; }
section() {
    echo
    print_color "$MAGENTA" "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    print_color "$MAGENTA" "  $*"
    print_color "$MAGENTA" "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo
}

# ── Helpers ───────────────────────────────────────────────────────────────
gssh() {
    gcloud --account="$GCP_ACCOUNT" --project="$GCP_PROJECT" \
        compute ssh "$REMOTE_USER@$GCP_VM" --zone="$GCP_ZONE" \
        --command="$1"
}

gssh_heredoc() {
    gcloud --account="$GCP_ACCOUNT" --project="$GCP_PROJECT" \
        compute ssh "$REMOTE_USER@$GCP_VM" --zone="$GCP_ZONE" \
        -- "bash -s"
}

show_help() {
    cat <<EOF
Family Task Manager — GCP Deployment

Target VM: $GCP_VM (project=$GCP_PROJECT, zone=$GCP_ZONE)

Usage:
  ./scripts/deploy-gcp.sh [OPTIONS]

Options:
  -y, --yes                  Skip confirmation prompts
  --skip-backup              Skip pre-deploy database backup
  --skip-migrations          Skip alembic upgrade head
  --skip-build               Use cached docker images
  --seed                     Run seed_data.py post-migrate (DESTRUCTIVE on existing data)
  --logs                     Tail container logs after deploy
  --tail N                   Lines of logs to show (default: $LOG_TAIL)
  -h, --help                 Show this help

Override defaults via .deploy.gcp.env or env vars (see top of script).
EOF
}

parse_arguments() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            -y|--yes)           SKIP_CONFIRMATION=true; shift ;;
            --skip-backup)      SKIP_BACKUP=true; shift ;;
            --skip-migrations)  SKIP_MIGRATIONS=true; shift ;;
            --skip-build)       SKIP_BUILD=true; shift ;;
            --seed)             SKIP_SEED=false; shift ;;
            --logs)             SHOW_LOGS=true; shift ;;
            --tail)             LOG_TAIL=$2; shift 2 ;;
            -h|--help)          show_help; exit 0 ;;
            *)                  error "Unknown option: $1"; show_help; exit 1 ;;
        esac
    done
}

# ── Pre-flight (local) ────────────────────────────────────────────────────
check_local() {
    section "Pre-flight Checks (Local)"

    [[ -f "$PROJECT_ROOT/$COMPOSE_FILE" ]] \
        || { error "Missing $COMPOSE_FILE at project root"; exit 1; }
    success "$COMPOSE_FILE present"

    command -v gcloud >/dev/null 2>&1 \
        || { error "gcloud CLI not installed"; exit 1; }
    success "gcloud available"

    command -v rsync >/dev/null 2>&1 \
        || { error "rsync not installed"; exit 1; }
    success "rsync available"

    info "Verifying VM is reachable…"
    if ! gcloud --account="$GCP_ACCOUNT" --project="$GCP_PROJECT" \
            compute instances describe "$GCP_VM" --zone="$GCP_ZONE" \
            --format="value(status)" 2>/dev/null | grep -q RUNNING; then
        error "VM $GCP_VM is not RUNNING"
        exit 1
    fi
    success "VM $GCP_VM is RUNNING"

    mkdir -p "$LOG_DIR"
}

# ── Pre-flight (remote) ───────────────────────────────────────────────────
check_remote() {
    section "Pre-flight Checks (Remote)"

    info "Ensuring remote path exists…"
    gssh "mkdir -p $REMOTE_PATH"
    success "Remote path: $REMOTE_PATH"

    info "Checking docker on remote…"
    if ! gssh "sudo docker info >/dev/null 2>&1"; then
        error "Docker not running on VM. Run scripts/gcp-bootstrap.sh first."
        exit 1
    fi
    success "Docker is up"
}

# ── Confirm ───────────────────────────────────────────────────────────────
confirm() {
    [[ "$SKIP_CONFIRMATION" == "true" ]] && return 0
    echo
    print_color "$RED" "⚠️⚠️⚠️  DEPLOY TO GCP PRODUCTION  ⚠️⚠️⚠️"
    echo "  VM:      $GCP_VM ($GCP_ZONE / $GCP_PROJECT)"
    echo "  Path:    $REMOTE_PATH"
    echo "  Compose: $COMPOSE_FILE"
    [[ "$SKIP_BACKUP" == "true" ]]     && warning "Pre-deploy DB backup SKIPPED"
    [[ "$SKIP_MIGRATIONS" == "true" ]] && warning "Alembic migrations SKIPPED"
    [[ "$SKIP_BUILD" == "true" ]]      && info    "Using cached images"
    [[ "$SKIP_SEED" == "false" ]]      && warning "Will run seed_data.py (overwrites demo accounts)"
    echo
    read -r -p "Type 'DEPLOY' to continue: " REPLY
    [[ "$REPLY" == "DEPLOY" ]] || { error "Cancelled"; exit 0; }
}

# ── Backup DB ─────────────────────────────────────────────────────────────
backup_db() {
    section "Backing Up Database"
    gssh_heredoc <<ENDSSH
set -e
cd $REMOTE_PATH
sudo mkdir -p backups/pre-deploy
BACKUP_FILE="backups/pre-deploy/backup-\$(date +%Y%m%d-%H%M%S).sql"
if sudo docker compose --env-file .env -f $COMPOSE_FILE ps postgres 2>/dev/null | grep -q "Up"; then
    set -a; source .env; set +a
    sudo docker compose --env-file .env -f $COMPOSE_FILE exec -T postgres \
        pg_dump -U "\$POSTGRES_USER" "\$POSTGRES_DB" | sudo tee "\$BACKUP_FILE" >/dev/null
    echo "Backup: \$BACKUP_FILE (\$(du -h "\$BACKUP_FILE" | cut -f1))"
    ls -t backups/pre-deploy/*.sql 2>/dev/null | tail -n +11 | xargs -r sudo rm -f
else
    echo "postgres container not running, skipping backup"
fi
ENDSSH
    success "Backup step done"
}

# ── Rsync code ────────────────────────────────────────────────────────────
sync_code() {
    section "Syncing Code"

    info "Resolving VM external IP…"
    VM_IP=$(gcloud --account="$GCP_ACCOUNT" --project="$GCP_PROJECT" \
        compute instances describe "$GCP_VM" --zone="$GCP_ZONE" \
        --format='value(networkInterfaces[0].accessConfigs[0].natIP)')
    [[ -n "$VM_IP" ]] || { error "Could not get VM external IP"; exit 1; }
    success "VM IP: $VM_IP"

    # Ensure gcloud has provisioned an SSH key + added it to instance metadata.
    gcloud --account="$GCP_ACCOUNT" --project="$GCP_PROJECT" \
        compute ssh "$REMOTE_USER@$GCP_VM" --zone="$GCP_ZONE" \
        --command='true' >/dev/null 2>&1 || true

    SSH_KEY="$HOME/.ssh/google_compute_engine"
    [[ -f "$SSH_KEY" ]] || { error "Missing $SSH_KEY (gcloud SSH key)"; exit 1; }

    info "Rsyncing project to VM ($REMOTE_USER@$VM_IP)…"
    rsync -avz --delete \
        --exclude='.git/' \
        --exclude='node_modules/' \
        --exclude='__pycache__/' \
        --exclude='*.pyc' \
        --exclude='.venv/' \
        --exclude='venv/' \
        --exclude='dist/' \
        --exclude='.astro/' \
        --exclude='logs/' \
        --exclude='backups/' \
        --exclude='htmlcov/' \
        --exclude='playwright-report/' \
        --exclude='test-results/' \
        --exclude='e2e-tests/' \
        --exclude='actual/' \
        --exclude='.env' \
        --exclude='.env.local' \
        --exclude='.deploy.gcp.env' \
        -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$HOME/.ssh/google_compute_known_hosts" \
        "$PROJECT_ROOT/" \
        "$REMOTE_USER@$VM_IP:$REMOTE_PATH/" 2>&1 | tee -a "$LOG_FILE"

    success "Code synced"
}

# ── Build & start ─────────────────────────────────────────────────────────
build_and_start() {
    section "Building and Starting Services"
    gssh_heredoc <<ENDSSH
set -e
cd $REMOTE_PATH

if [[ ! -f .env ]]; then
    echo "❌ .env missing on VM at $REMOTE_PATH/.env"
    echo "   Copy .env.gcp.example → .env and fill in secrets first."
    exit 1
fi

if [[ "$SKIP_BUILD" != "true" ]]; then
    echo "🏗️  Building images…"
    sudo docker compose --env-file .env -f $COMPOSE_FILE build --no-cache backend frontend
fi

echo "🚀 Starting services…"
sudo docker compose --env-file .env -f $COMPOSE_FILE up -d

echo "⏳ Waiting for healthchecks (max 180s)…"
CRITICAL=(postgres redis backend frontend)
TIMEOUT=180; ELAPSED=0
while [[ \$ELAPSED -lt \$TIMEOUT ]]; do
    PS_JSON=\$(sudo docker compose --env-file .env -f $COMPOSE_FILE ps --format json 2>/dev/null)
    ALL_OK=true
    for svc in "\${CRITICAL[@]}"; do
        if ! echo "\$PS_JSON" | grep -E "\"Service\":\"\$svc\"" | grep -q '"Health":"healthy"'; then
            ALL_OK=false; break
        fi
    done
    \$ALL_OK && break
    sleep 3; ELAPSED=\$((ELAPSED+3)); echo -n "."
done
echo

sudo docker compose --env-file .env -f $COMPOSE_FILE ps
ENDSSH
    success "Services running"
}

# ── Migrate ───────────────────────────────────────────────────────────────
migrate() {
    section "Running Alembic Migrations"
    gssh_heredoc <<ENDSSH
set -e
cd $REMOTE_PATH
sudo docker compose --env-file .env -f $COMPOSE_FILE exec -T backend alembic upgrade head
sudo docker compose --env-file .env -f $COMPOSE_FILE exec -T backend alembic current
ENDSSH
    success "Migrations done"
}

# ── Seed (opt-in) ─────────────────────────────────────────────────────────
seed() {
    section "Seeding Demo Data"
    warning "This creates demo families (mom/dad/emma/lucas)."
    gssh_heredoc <<ENDSSH
set -e
cd $REMOTE_PATH
sudo docker compose --env-file .env -f $COMPOSE_FILE exec -T backend python /app/seed_data.py
ENDSSH
    success "Seed done"
}

# ── Verify ────────────────────────────────────────────────────────────────
verify() {
    section "Verification"

    info "Public endpoints (via Cloudflare Tunnel):"
    for url in "https://gcp-family.agent-ia.mx" "https://api-gcp-family.agent-ia.mx/health"; do
        STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$url" 2>/dev/null || echo "000")
        if [[ "$STATUS" =~ ^(200|301|302|404)$ ]]; then
            success "$url → HTTP $STATUS"
        else
            warning "$url → HTTP $STATUS (tunnel/DNS may still be propagating)"
        fi
    done

    info "Container status:"
    gssh "cd $REMOTE_PATH && sudo docker compose --env-file .env -f $COMPOSE_FILE ps"
}

# ── Logs ──────────────────────────────────────────────────────────────────
tail_logs() {
    section "Recent Logs (tail $LOG_TAIL)"
    gssh "cd $REMOTE_PATH && sudo docker compose --env-file .env -f $COMPOSE_FILE logs --tail=$LOG_TAIL"
}

# ── Summary ───────────────────────────────────────────────────────────────
summary() {
    section "Deployment Summary"
    success "Deploy complete"
    echo
    print_color "$CYAN" "📍 URLs:"
    echo "   Frontend:  https://gcp-family.agent-ia.mx"
    echo "   API:       https://api-gcp-family.agent-ia.mx"
    echo "   API docs:  https://api-gcp-family.agent-ia.mx/docs"
    echo
    print_color "$CYAN" "🔧 Ops:"
    echo "   Logs:    gcloud compute ssh $GCP_VM --zone=$GCP_ZONE --command='cd $REMOTE_PATH && sudo docker compose --env-file .env -f $COMPOSE_FILE logs -f'"
    echo "   Status:  gcloud compute ssh $GCP_VM --zone=$GCP_ZONE --command='cd $REMOTE_PATH && sudo docker compose --env-file .env -f $COMPOSE_FILE ps'"
    echo
    info "Log: $LOG_FILE"
}

# ── Main ──────────────────────────────────────────────────────────────────
main() {
    parse_arguments "$@"
    section "Family Task Manager — GCP Deploy"
    check_local
    check_remote
    confirm
    [[ "$SKIP_BACKUP"     == "true" ]] || backup_db
    sync_code
    build_and_start
    [[ "$SKIP_MIGRATIONS" == "true" ]] || migrate
    [[ "$SKIP_SEED"       == "true" ]] || seed
    verify
    [[ "$SHOW_LOGS"       == "true" ]] && tail_logs
    summary
}

main "$@"
