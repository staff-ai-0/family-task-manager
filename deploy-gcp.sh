#!/bin/bash
#
# Family Task Manager - GCP Deployment Script
# Deploys to shared GCP VM alongside school-admin.
# Usage: ./deploy-gcp.sh
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}i${NC} $1"; }
log_success() { echo -e "${GREEN}ok${NC} $1"; }
log_warning() { echo -e "${YELLOW}!!${NC} $1"; }
log_error()   { echo -e "${RED}x${NC} $1"; }

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

DC="sudo docker compose --env-file .env -f docker-compose.gcp.yml"

echo ""
echo "=========================================="
echo "FAMILY TASK MANAGER - GCP DEPLOYMENT"
echo "=========================================="
echo "Time: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# Pre-flight checks
if [ ! -f .env ]; then
    log_error ".env file not found. Copy .env.gcp.example to .env and fill in values."
    exit 1
fi

# Check platform-network exists (created by platform docker-compose)
if ! sudo docker network inspect platform-network >/dev/null 2>&1; then
    log_error "External network 'platform-network' not found. Is the platform stack running?"
    exit 1
fi

# Check shared services are up
for svc in platform-postgres platform-redis platform-vault litellm-proxy; do
    if sudo docker inspect --format='{{.State.Running}}' "$svc" 2>/dev/null | grep -q true; then
        log_success "$svc is running"
    else
        log_warning "$svc is not running — deployment may fail"
    fi
done

# Step 1: Pull latest code
log_info "Step 1/6: Pulling latest code..."
git fetch origin main
git reset --hard origin/main
COMMIT=$(git log --oneline -1)
log_success "Code updated: $COMMIT"
echo ""

# Step 2: Build backend + frontend
log_info "Step 2/6: Building images..."
if $DC build --no-cache backend frontend > /tmp/ftm_gcp_build.log 2>&1; then
    log_success "Images built"
else
    log_error "Build failed — last 40 lines:"
    tail -40 /tmp/ftm_gcp_build.log
    exit 1
fi
echo ""

# Step 3: Start / recreate containers
log_info "Step 3/6: Starting stack (backend, frontend, tunnel)..."
$DC up -d > /tmp/ftm_gcp_up.log 2>&1
log_success "Stack started"
echo ""

# Step 4: Wait for backend to be healthy
log_info "Step 4/6: Waiting for backend to be healthy..."
for i in {1..60}; do
    if $DC exec -T backend curl -sf http://localhost:8000/docs >/dev/null 2>&1; then
        log_success "Backend is healthy"
        break
    fi
    if [ $i -eq 60 ]; then
        log_error "Backend failed to become healthy"
        $DC logs --tail=30 backend
        exit 1
    fi
    echo -n "."
    sleep 2
done
echo ""

# Step 5: Run Alembic migrations
log_info "Step 5/6: Running database migrations..."
if $DC exec -T backend alembic upgrade head > /tmp/ftm_gcp_migrations.log 2>&1; then
    log_success "Migrations applied"
else
    log_error "Migrations failed:"
    cat /tmp/ftm_gcp_migrations.log
    exit 1
fi
echo ""

# Step 6: Health checks
log_info "Step 6/6: Running health checks..."
sleep 3

BACKEND_OK=false
FRONTEND_OK=false

if $DC exec -T backend curl -sf http://localhost:8000/docs >/dev/null 2>&1; then
    log_success "Backend healthy"
    BACKEND_OK=true
else
    log_warning "Backend health check failed"
fi

if $DC exec -T frontend curl -sf http://localhost:3000/ >/dev/null 2>&1; then
    log_success "Frontend healthy"
    FRONTEND_OK=true
else
    log_warning "Frontend health check failed"
fi

RUNNING=$(sudo docker ps --format "{{.Names}}" | grep -c "gcp_ftm" || true)
log_info "${RUNNING} gcp_ftm_* containers running"
echo ""

if [ "$BACKEND_OK" = true ] && [ "$FRONTEND_OK" = true ]; then
    log_success "DEPLOYMENT COMPLETED SUCCESSFULLY!"
else
    log_warning "Deployment finished with warnings — check logs above"
fi

echo ""
echo "Running services:"
$DC ps --format "table {{.Name}}\t{{.Status}}"
echo ""
echo "Access:"
echo "   Public:   https://family.agent-ia.mx"
echo "   API:      https://fam-backend.agent-ia.mx"
echo ""
echo "Commands:"
echo "   Logs:     $DC logs -f backend"
echo "   Restart:  $DC restart backend frontend"
echo "   Shell:    $DC exec backend bash"
echo ""
echo "=========================================="
echo "DEPLOYMENT COMPLETE"
echo "Time: $(date '+%Y-%m-%d %H:%M:%S')"
echo "=========================================="
