#!/bin/bash
#
# Family Task Manager - Deployment Script
# ========================================
# This script is parsed by the /deploy command to extract server configuration.
# It can also be run manually for deployment operations.
#
# Usage:
#   ./scripts/deploy.sh [dev|stage|prod]
#
# Environment Variables (from Vault):
#   - DATABASE_URL
#   - SECRET_KEY
#   - JWT_SECRET_KEY
#   - GOOGLE_CLIENT_ID
#   - GOOGLE_CLIENT_SECRET
#   - SMTP_* (email configuration)
#

set -e

# ==============================================================================
# SERVER CONFIGURATION
# ==============================================================================
# These variables are parsed by the /deploy command

STAGE_SERVER="jc@10.1.0.91"
STAGE_PATH="/home/jc/family-task-manager"

PROD_SERVER="jc@10.1.0.92"
PROD_PATH="/home/jc/family-task-manager"

# Application ports (Python/Uvicorn)
BACKEND_PORT=8000
FRONTEND_PORT=3000

# Docker ports (PostgreSQL, Redis)
DB_PORT=5433
REDIS_PORT=6380

# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# ==============================================================================
# ENVIRONMENT SELECTION
# ==============================================================================

ENV=${1:-dev}

case $ENV in
    dev)
        log_info "Deploying to LOCAL DEVELOPMENT environment"
        SERVER=""
        DEPLOY_PATH="."
        ;;
    stage)
        log_info "Deploying to STAGING environment"
        SERVER=$STAGE_SERVER
        DEPLOY_PATH=$STAGE_PATH
        ;;
    prod)
        log_info "Deploying to PRODUCTION environment"
        SERVER=$PROD_SERVER
        DEPLOY_PATH=$PROD_PATH
        ;;
    *)
        log_error "Unknown environment: $ENV"
        echo "Usage: $0 [dev|stage|prod]"
        exit 1
        ;;
esac

# ==============================================================================
# DEPLOYMENT FUNCTIONS
# ==============================================================================

deploy_local() {
    log_info "Starting local Docker containers..."
    docker-compose up -d
    
    log_info "Waiting for services to be healthy..."
    sleep 10
    
    log_info "Running database migrations..."
    docker exec family_app_backend alembic upgrade head
    
    log_info "Local deployment complete!"
    echo ""
    echo "URLs:"
    echo "  Frontend: http://localhost:$FRONTEND_PORT"
    echo "  Backend:  http://localhost:$BACKEND_PORT"
    echo "  API Docs: http://localhost:$BACKEND_PORT/docs"
}

deploy_remote() {
    local server=$1
    local path=$2
    local env=$3
    
    log_info "Deploying to $server:$path"
    
    # Check SSH connection
    if ! ssh -o ConnectTimeout=10 -o BatchMode=yes $server "echo ok" > /dev/null 2>&1; then
        log_error "Cannot connect to $server"
        exit 1
    fi
    
    # Check if repo exists
    if ! ssh $server "test -d $path/.git"; then
        log_info "Repository not found. Cloning..."
        REMOTE_URL=$(git remote get-url origin)
        ssh $server "git clone $REMOTE_URL $path"
    fi
    
    # Pull latest code
    log_info "Pulling latest code..."
    BRANCH=$(git branch --show-current)
    ssh $server "cd $path && git fetch origin && git checkout $BRANCH && git pull origin $BRANCH"
    
    # Copy environment file
    log_info "Copying environment configuration..."
    scp .env $server:$path/.env
    
    # Start Docker containers (database, redis)
    log_info "Starting Docker containers..."
    ssh $server "cd $path && docker compose -f docker-compose.${env}.yml up -d"
    
    log_info "Waiting for containers to be healthy..."
    sleep 15
    
    # Run database migrations
    log_info "Running database migrations..."
    ssh $server "cd $path && docker exec family_app_backend alembic upgrade head"
    
    # Restart PM2 applications
    log_info "Restarting PM2 applications..."
    ssh $server "cd $path && pm2 delete family-backend family-frontend 2>/dev/null || true"
    ssh $server "cd $path && export \$(grep -v '^#' .env | xargs) && pm2 start ecosystem.config.cjs --env $env && pm2 save"
    
    log_info "Deployment complete!"
}

# ==============================================================================
# MAIN
# ==============================================================================

if [ "$ENV" == "dev" ]; then
    deploy_local
else
    deploy_remote $SERVER $DEPLOY_PATH $ENV
fi
