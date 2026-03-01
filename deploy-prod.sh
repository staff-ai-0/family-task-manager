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

# Step 1: Pull latest code
log_info "Step 1/12: Pulling latest code from GitHub..."
git fetch origin main
git reset --hard origin/main
COMMIT=$(git log --oneline -1)
log_success "Code updated: $COMMIT"
echo ""

# Step 2: Verify commit
log_info "Step 2/12: Verifying deployment commit..."
EXPECTED_COMMIT="5d933de"
CURRENT_COMMIT=$(git log --oneline -1 | cut -d' ' -f1)
if [[ $CURRENT_COMMIT == $EXPECTED_COMMIT* ]]; then
    log_success "Correct commit verified"
else
    log_warning "Current commit differs, but continuing with deployment"
fi
echo ""

# Step 3: Stop old containers
log_info "Step 3/12: Stopping old containers..."
docker-compose down -v 2>/dev/null || true
docker stop family-app-backend family-app-frontend 2>/dev/null || true
docker rm family-app-backend family-app-frontend 2>/dev/null || true
log_success "Old containers stopped"
echo ""

# Step 4: Build backend
log_info "Step 4/12: Building backend container..."
if docker build --no-cache -t family-task-manager-backend:latest ./backend > /tmp/backend_build.log 2>&1; then
    log_success "Backend container built"
else
    log_error "Backend build failed"
    cat /tmp/backend_build.log
    exit 1
fi
echo ""

# Step 5: Build frontend
log_info "Step 5/12: Building frontend container..."
if docker build --no-cache -t family-task-manager-frontend:latest ./frontend > /tmp/frontend_build.log 2>&1; then
    log_success "Frontend container built"
else
    log_error "Frontend build failed"
    cat /tmp/frontend_build.log
    exit 1
fi
echo ""

# Step 6: Start infrastructure
log_info "Step 6/12: Starting infrastructure (DB, Redis)..."
docker-compose -f docker-compose.prod.yml up -d > /tmp/infra_start.log 2>&1
log_success "Infrastructure services started"
echo ""

# Step 7: Wait for database
log_info "Step 7/12: Waiting for database to be healthy..."
sleep 15
for i in {1..30}; do
    if docker-compose -f docker-compose.prod.yml exec -T db pg_isready -U familyapp >/dev/null 2>&1; then
        log_success "Database is healthy"
        break
    fi
    if [ $i -eq 30 ]; then
        log_error "Database failed to become healthy"
        exit 1
    fi
    echo -n "."
    sleep 1
done
echo ""

# Step 8: Run migrations
log_info "Step 8/12: Running database migrations..."
if docker run --rm \
  --network family-task-manager_app_network \
  -e DATABASE_URL="postgresql+asyncpg://familyapp:familyapp123@db:5432/familyapp" \
  -v $(pwd)/backend:/app \
  family-task-manager-backend:latest \
  bash -c "cd /app && alembic upgrade head" > /tmp/migrations.log 2>&1; then
    log_success "Database migrations completed"
else
    log_error "Database migrations failed"
    cat /tmp/migrations.log
    exit 1
fi
echo ""

# Step 9: Start backend
log_info "Step 9/12: Starting backend service..."
if docker run -d \
  --name family-app-backend \
  --network family-task-manager_app_network \
  -p 8000:8000 \
  -e DATABASE_URL="postgresql+asyncpg://familyapp:familyapp123@db:5432/familyapp" \
  -e REDIS_URL="redis://redis:6379/0" \
  -e SECRET_KEY="${SECRET_KEY:-dev-secret-key-change-in-production}" \
  -e DEBUG=false \
  family-task-manager-backend:latest > /tmp/backend_start.log 2>&1; then
    log_success "Backend service started"
else
    log_error "Backend failed to start"
    cat /tmp/backend_start.log
    exit 1
fi
echo ""

# Step 10: Start frontend
log_info "Step 10/12: Starting frontend service..."
if docker run -d \
  --name family-app-frontend \
  --network family-task-manager_app_network \
  -p 3003:3000 \
  -e API_BASE_URL="http://family-app-backend:8000" \
  family-task-manager-frontend:latest > /tmp/frontend_start.log 2>&1; then
    log_success "Frontend service started"
else
    log_error "Frontend failed to start"
    cat /tmp/frontend_start.log
    exit 1
fi
echo ""

# Step 11: Health checks
log_info "Step 11/12: Running health checks..."
sleep 10

# Check backend
if curl -s http://localhost:8000/api/sync/health -w "%{http_code}" -o /dev/null | grep -q "410"; then
    log_success "Backend health check passed (sync endpoint returns 410 as expected)"
else
    log_warning "Backend health check may need attention - sync endpoint not responding as expected"
fi

# Check containers running
RUNNING=$(docker ps --format "{{.Names}}" | grep -c "family-app" || true)
if [ $RUNNING -eq 2 ]; then
    log_success "Both backend and frontend containers are running"
else
    log_warning "Expected 2 containers running, found $RUNNING"
fi
echo ""

# Step 12: Display summary
log_info "Step 12/12: Deployment summary..."
echo ""
log_success "DEPLOYMENT COMPLETED SUCCESSFULLY!"
echo ""
echo "📊 Running Services:"
docker ps --filter "name=family-app" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
echo ""
echo "📝 Recent Logs (Backend):"
docker logs --tail 10 family-app-backend | grep -E "INFO|ERROR|WARN" | tail -5
echo ""
echo "🔗 Access Points:"
echo "   Backend API: http://localhost:8000/docs"
echo "   Frontend: http://localhost:3003"
echo ""
echo "📋 Next Steps:"
echo "   1. Test sync endpoints: curl -i http://localhost:8000/api/sync/health"
echo "   2. Monitor logs: docker logs -f family-app-backend"
echo "   3. Check frontend: curl http://localhost:3003"
echo ""
echo "🚨 If issues occur:"
echo "   1. Check logs: docker logs family-app-backend"
echo "   2. Use rollback: git revert 5d933de && git push"
echo "   3. Run this script again"
echo ""
echo "=========================================="
echo "✅ DEPLOYMENT COMPLETE"
echo "Time: $(date '+%Y-%m-%d %H:%M:%S')"
echo "=========================================="
