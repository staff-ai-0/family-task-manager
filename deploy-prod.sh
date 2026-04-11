#!/bin/bash
#
# Family Task Manager - Production Deployment Script
# Deploys Phase 10 & Phase 11 changes to production
# Usage: ./deploy-prod.sh
#

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Functions
log_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

log_success() {
    echo -e "${GREEN}✅${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

log_error() {
    echo -e "${RED}✗${NC} $1"
}

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo ""
echo "=========================================="
echo "🚀 FAMILY TASK MANAGER - PRODUCTION DEPLOYMENT"
echo "=========================================="
echo "Time: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# This script is intended to run ON the production host (10.1.0.99),
# from inside /mnt/nvme/docker-prod/family-task-manager. It drives the
# stack via docker-compose.yml (the only prod-ready compose file).

# Sudo for docker (required on prod host)
DC="sudo docker compose"

# Step 1: Pull latest code
log_info "Step 1/6: Pulling latest code from GitHub..."
git fetch origin main
git reset --hard origin/main
COMMIT=$(git log --oneline -1)
log_success "Code updated: $COMMIT"
echo ""

# Step 2: Build backend + frontend (no-cache for a clean prod build)
log_info "Step 2/6: Building backend & frontend images..."
if $DC build --no-cache backend frontend > /tmp/ftm_build.log 2>&1; then
    log_success "Images built"
else
    log_error "Build failed — last 40 lines:"
    tail -40 /tmp/ftm_build.log
    exit 1
fi
echo ""

# Step 3: Start / recreate the stack
# NOTE: No `down -v`. That would destroy the postgres_data volume on every
# deploy. We just `up -d`, which recreates containers whose image changed.
log_info "Step 3/6: Starting stack (db, test_db, redis, backend, frontend)..."
$DC up -d > /tmp/ftm_up.log 2>&1
log_success "Stack started"
echo ""

# Step 4: Wait for db to be healthy before running migrations
log_info "Step 4/6: Waiting for database to be healthy..."
for i in {1..45}; do
    if $DC exec -T db pg_isready -U familyapp >/dev/null 2>&1; then
        log_success "Database is healthy"
        break
    fi
    if [ $i -eq 45 ]; then
        log_error "Database failed to become healthy"
        $DC logs --tail=30 db
        exit 1
    fi
    echo -n "."
    sleep 1
done
echo ""

# Step 5: Run Alembic migrations inside the running backend container
log_info "Step 5/6: Running database migrations..."
# Give backend a moment to finish its own startup
sleep 5
if $DC exec -T backend alembic upgrade head > /tmp/ftm_migrations.log 2>&1; then
    log_success "Migrations applied"
else
    log_error "Migrations failed — full output:"
    cat /tmp/ftm_migrations.log
    exit 1
fi
echo ""

# Step 6: Health checks
log_info "Step 6/6: Running health checks..."
sleep 5

# /api/sync/health is intentionally 410 Gone post Phase 10 (see CLAUDE.md).
# It's our canonical "backend is serving" ping.
if curl -s -o /dev/null -w "%{http_code}" http://localhost:8003/api/sync/health | grep -q "410"; then
    log_success "Backend reachable (sync endpoint returns 410 as expected)"
else
    log_warning "Backend /api/sync/health did not return 410"
fi

if curl -sf -o /dev/null http://localhost:3003/; then
    log_success "Frontend reachable on :3003"
else
    log_warning "Frontend /:3003 not responding"
fi

RUNNING=$(sudo docker ps --format "{{.Names}}" | grep -c "^family_app_" || true)
if [ "$RUNNING" -ge 4 ]; then
    log_success "${RUNNING} family_app_* containers running"
else
    log_warning "Expected ≥4 family_app_* containers, found $RUNNING"
fi
echo ""

log_success "DEPLOYMENT COMPLETED SUCCESSFULLY!"
echo ""
echo "Running services:"
sudo docker ps --filter "name=family_app" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
echo ""
echo "Access points:"
echo "   Backend API:  http://localhost:8003/docs"
echo "   Frontend:     http://localhost:3003"
echo "   Public URL:   https://family.agent-ia.mx"
echo ""
echo "Useful commands:"
echo "   Logs:         $DC logs -f backend"
echo "   Restart:      $DC restart backend frontend"
echo "   Shell (be):   $DC exec backend bash"
echo ""
echo "=========================================="
echo "✅ DEPLOYMENT COMPLETE"
echo "Time: $(date '+%Y-%m-%d %H:%M:%S')"
echo "=========================================="
