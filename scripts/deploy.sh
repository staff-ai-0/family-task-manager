#!/bin/bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ==============================================================================
# SERVER CONFIGURATION
# ==============================================================================

STAGE_SERVER="jc@10.1.0.91"
STAGE_PATH="/home/jc/family-task-manager"

PROD_SERVER="jc@10.1.0.92"
PROD_PATH="/home/jc/family-task-manager"

# Application ports
BACKEND_PORT=8000
FRONTEND_PORT=3000
FINANCE_API_PORT=5007

# Infrastructure ports (Docker)
DB_PORT=5433
REDIS_PORT=6380
ACTUAL_BUDGET_PORT=5006

# PM2 app names
PM2_APPS="family-backend family-frontend family-finance-api"

# ==============================================================================
# ARGUMENT PARSING
# ==============================================================================

ENV=""
SKIP_BUILD=false
QUICK_MODE=false
DRY_RUN=false
SKIP_BACKUP=false
SKIP_MIGRATIONS=false
BACKUP_VERIFICATION=true
CHECK_INFRA=true

show_help() {
    echo "Usage: $0 <stage|prod> [OPTIONS]"
    echo ""
    echo "Environments:"
    echo "  stage                     Deploy to staging (10.1.0.91)"
    echo "  prod                      Deploy to production (10.1.0.92)"
    echo ""
    echo "Options:"
    echo "  --skip-build              Skip frontend build and pip install"
    echo "  --quick                   Quick mode: skip cleanup and use cached deps"
    echo "  --dry-run                 Show what would be deployed without making changes"
    echo "  --skip-backup             Skip database backup (NOT recommended)"
    echo "  --skip-migrations         Skip database migrations"
    echo "  --no-backup-verification  Skip backup verification step"
    echo "  --skip-infra-check        Skip infrastructure health checks"
    echo "  --help                    Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 stage                        # Full staging deployment"
    echo "  $0 stage --dry-run              # Preview staging deployment"
    echo "  $0 stage --quick --skip-build   # Fast deploy (existing build)"
    echo "  $0 prod                         # Full production deployment"
    echo ""
    echo "Architecture:"
    echo "  Infrastructure (Docker):  PostgreSQL, Redis, Actual Budget Server"
    echo "  Applications (PM2):       Backend (FastAPI), Frontend (Astro 5), Finance API"
}

# First argument must be environment
if [ $# -eq 0 ]; then
    show_help
    exit 1
fi

case $1 in
    stage|prod)
        ENV=$1
        shift
        ;;
    --help)
        show_help
        exit 0
        ;;
    *)
        echo -e "${RED}First argument must be 'stage' or 'prod', got: $1${NC}"
        show_help
        exit 1
        ;;
esac

# Parse remaining options
while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-build)
            SKIP_BUILD=true
            shift
            ;;
        --quick)
            QUICK_MODE=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --skip-backup)
            SKIP_BACKUP=true
            shift
            ;;
        --skip-migrations)
            SKIP_MIGRATIONS=true
            shift
            ;;
        --no-backup-verification)
            BACKUP_VERIFICATION=false
            shift
            ;;
        --skip-infra-check)
            CHECK_INFRA=false
            shift
            ;;
        --help)
            show_help
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            echo "Run '$0 --help' for usage information"
            exit 1
            ;;
    esac
done

# Set environment-specific variables
if [ "$ENV" = "stage" ]; then
    REMOTE_SERVER=$STAGE_SERVER
    REMOTE_PATH=$STAGE_PATH
    COMPOSE_FILE="docker-compose.stage.yml"
    PM2_ENV="stage"
    BASE_URL="https://fam-stage.a-ai4all.com"
    ENV_LABEL="STAGING"
elif [ "$ENV" = "prod" ]; then
    REMOTE_SERVER=$PROD_SERVER
    REMOTE_PATH=$PROD_PATH
    COMPOSE_FILE="docker-compose.prod.yml"
    PM2_ENV="production"
    BASE_URL="https://fam.a-ai4all.com"
    ENV_LABEL="PRODUCTION"
fi

REMOTE_HOST=$(echo $REMOTE_SERVER | cut -d@ -f2)
REMOTE_USER=$(echo $REMOTE_SERVER | cut -d@ -f1)
REMOTE_BRANCH="main"

# ==============================================================================
# HEADER
# ==============================================================================

echo -e "${BLUE}Family Task Manager - ${ENV_LABEL} Deployment${NC}"
echo "========================================"
echo "Date:   $(date '+%Y-%m-%d %H:%M:%S')"
echo "Target: ${REMOTE_SERVER}:${REMOTE_PATH}"
echo "Branch: ${REMOTE_BRANCH}"
echo "Config: ${COMPOSE_FILE} (infra) + PM2 (apps)"
echo ""

if [ "$DRY_RUN" = true ]; then
    echo -e "${YELLOW}DRY-RUN MODE: No changes will be made${NC}"
    echo ""
fi

# ==============================================================================
# PRE-DEPLOYMENT CHECKS
# ==============================================================================

echo -e "${YELLOW}Pre-deployment checks...${NC}"

# Check SSH connection
if ! ssh -o BatchMode=yes -o ConnectTimeout=5 ${REMOTE_SERVER} exit &> /dev/null; then
    echo -e "${RED}Cannot connect to ${REMOTE_SERVER}${NC}"
    echo "Please ensure SSH key authentication is set up"
    exit 1
fi
echo -e "${GREEN}  SSH connection OK${NC}"

# Check current branch
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$CURRENT_BRANCH" != "$REMOTE_BRANCH" ]; then
    echo -e "${YELLOW}  Warning: Current branch is '${CURRENT_BRANCH}', deploying '${REMOTE_BRANCH}'${NC}"
fi

# Check for uncommitted changes
if [ -n "$(git status --porcelain)" ]; then
    echo -e "${RED}  You have uncommitted changes${NC}"
    echo "Please commit or stash your changes before deploying"
    git status --short
    exit 1
fi
echo -e "${GREEN}  Git repository is clean${NC}"

# Check .env exists on remote
if ssh ${REMOTE_SERVER} "[ -f ${REMOTE_PATH}/.env ]"; then
    echo -e "${GREEN}  Remote .env exists${NC}"
else
    echo -e "${YELLOW}  Warning: No .env on remote. Will copy local .env if available${NC}"
fi

# ==============================================================================
# INFRASTRUCTURE HEALTH CHECKS
# ==============================================================================

if [ "$CHECK_INFRA" = true ]; then
    echo ""
    echo -e "${YELLOW}Checking infrastructure on ${REMOTE_HOST}...${NC}"

    # Check PostgreSQL
    if ssh ${REMOTE_SERVER} "docker ps --format '{{.Names}}' | grep -q 'family_app_db'" 2>/dev/null; then
        echo -e "${GREEN}  PostgreSQL container is running${NC}"
    else
        echo -e "${YELLOW}  PostgreSQL container not found (will be started)${NC}"
    fi

    # Check Redis
    if ssh ${REMOTE_SERVER} "docker ps --format '{{.Names}}' | grep -q 'family_app_redis'" 2>/dev/null; then
        echo -e "${GREEN}  Redis container is running${NC}"
    else
        echo -e "${YELLOW}  Redis container not found (will be started)${NC}"
    fi

    # Check Actual Budget Server
    if ssh ${REMOTE_SERVER} "docker ps --format '{{.Names}}' | grep -q 'family_actual_budget'" 2>/dev/null; then
        echo -e "${GREEN}  Actual Budget server is running${NC}"
    else
        echo -e "${BLUE}  Actual Budget server not found (will be started)${NC}"
    fi

    # Check PM2
    if ssh ${REMOTE_SERVER} "command -v pm2" > /dev/null 2>&1; then
        echo -e "${GREEN}  PM2 is installed${NC}"
        # Show current PM2 status
        PM2_STATUS=$(ssh ${REMOTE_SERVER} "pm2 jlist 2>/dev/null | python3 -c \"
import sys, json
try:
    apps = json.load(sys.stdin)
    for app in apps:
        name = app.get('name', '?')
        status = app.get('pm2_env', {}).get('status', '?')
        print(f'    {name}: {status}')
except:
    print('    (no apps running)')
\"" 2>/dev/null || echo "    (unable to read status)")
        echo -e "${BLUE}  PM2 current status:${NC}"
        echo "$PM2_STATUS"
    else
        echo -e "${RED}  PM2 is NOT installed on remote${NC}"
        echo "Install with: ssh ${REMOTE_SERVER} 'npm install -g pm2'"
        exit 1
    fi

    # Check Node.js
    NODE_VERSION=$(ssh ${REMOTE_SERVER} "node --version 2>/dev/null" || echo "not found")
    echo -e "${BLUE}  Node.js: ${NODE_VERSION}${NC}"

    # Check Python venv
    if ssh ${REMOTE_SERVER} "[ -f ${REMOTE_PATH}/venv/bin/python3 ]"; then
        PYTHON_VERSION=$(ssh ${REMOTE_SERVER} "${REMOTE_PATH}/venv/bin/python3 --version 2>/dev/null" || echo "unknown")
        echo -e "${GREEN}  Python venv: ${PYTHON_VERSION}${NC}"
    else
        echo -e "${YELLOW}  Python venv not found at ${REMOTE_PATH}/venv${NC}"
        echo -e "${YELLOW}  Will need to create: python3 -m venv ${REMOTE_PATH}/venv${NC}"
    fi
fi

# ==============================================================================
# SYNC CODE VIA GIT
# ==============================================================================

echo ""
echo -e "${YELLOW}Syncing code via Git...${NC}"

if [ "$DRY_RUN" = true ]; then
    echo -e "${BLUE}[DRY-RUN] Would sync code from origin/${REMOTE_BRANCH}${NC}"
else
    if ssh ${REMOTE_SERVER} "[ -d ${REMOTE_PATH}/.git ]"; then
        echo -e "${BLUE}  Remote repository exists, pulling latest...${NC}"

        # Reset and pull
        ssh ${REMOTE_SERVER} "cd ${REMOTE_PATH} && git fetch origin ${REMOTE_BRANCH} && git reset --hard origin/${REMOTE_BRANCH}"

        if [ $? -ne 0 ]; then
            echo -e "${RED}  Git pull failed. Trying fresh clone...${NC}"
            BACKUP_PATH="${REMOTE_PATH}_backup_$(date +%Y%m%d_%H%M%S)"
            ssh ${REMOTE_SERVER} "mv ${REMOTE_PATH} ${BACKUP_PATH}"

            GIT_REMOTE=$(git config --get remote.origin.url)
            ssh ${REMOTE_SERVER} "git clone -b ${REMOTE_BRANCH} ${GIT_REMOTE} ${REMOTE_PATH}"

            # Restore .env if it existed
            ssh ${REMOTE_SERVER} "[ -f ${BACKUP_PATH}/.env ] && cp ${BACKUP_PATH}/.env ${REMOTE_PATH}/.env || true"
            echo -e "${YELLOW}  Old deployment backed up to: ${BACKUP_PATH}${NC}"
        fi
    else
        echo -e "${BLUE}  Cloning repository to remote...${NC}"
        GIT_REMOTE=$(git config --get remote.origin.url)
        ssh ${REMOTE_SERVER} "mkdir -p $(dirname ${REMOTE_PATH}) && git clone -b ${REMOTE_BRANCH} ${GIT_REMOTE} ${REMOTE_PATH}"
    fi

    echo -e "${GREEN}  Code synced successfully${NC}"
fi

# ==============================================================================
# DATABASE BACKUP
# ==============================================================================

if [ "$SKIP_BACKUP" = false ] && [ "$DRY_RUN" = false ]; then
    echo ""
    echo -e "${YELLOW}Creating database backup...${NC}"

    BACKUP_TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
    BACKUP_DIR="backups/pre-deploy-${BACKUP_TIMESTAMP}"

    ssh ${REMOTE_SERVER} << BACKUP_SCRIPT
        set -e
        cd ${REMOTE_PATH}
        mkdir -p ${BACKUP_DIR}

        # Check if db container is running
        if docker ps --format '{{.Names}}' | grep -q 'family_app_db'; then
            # Dump the database
            docker exec family_app_db pg_dump -U \${POSTGRES_USER:-familyapp} \${POSTGRES_DB:-familyapp} | gzip > ${BACKUP_DIR}/familyapp_${BACKUP_TIMESTAMP}.sql.gz
            echo "Backup created: ${BACKUP_DIR}/familyapp_${BACKUP_TIMESTAMP}.sql.gz"
        else
            echo "Database container not running, skipping backup"
        fi
BACKUP_SCRIPT

    if [ $? -eq 0 ]; then
        echo -e "${GREEN}  Database backup completed${NC}"

        # Verify backup
        if [ "$BACKUP_VERIFICATION" = true ]; then
            echo -e "${YELLOW}  Verifying backup integrity...${NC}"

            ssh ${REMOTE_SERVER} << VERIFY_SCRIPT
                cd ${REMOTE_PATH}/${BACKUP_DIR}

                BACKUP_FILES=\$(ls -1 *.sql.gz 2>/dev/null | wc -l)
                if [ "\$BACKUP_FILES" -eq 0 ]; then
                    echo "No backup files found (db may not have been running)"
                    exit 0
                fi

                BACKUP_SIZE=\$(du -k *.sql.gz | cut -f1 | head -1)
                if [ "\$BACKUP_SIZE" -lt 1 ]; then
                    echo "Backup file is too small (possibly corrupt)"
                    exit 1
                fi

                if ! gzip -t *.sql.gz 2>/dev/null; then
                    echo "Backup file is corrupted"
                    exit 1
                fi

                echo "Verification passed (files: \$BACKUP_FILES, size: \${BACKUP_SIZE}KB)"
VERIFY_SCRIPT

            if [ $? -eq 0 ]; then
                echo -e "${GREEN}  Backup verification passed${NC}"
            else
                echo -e "${RED}  Backup verification failed - aborting${NC}"
                exit 1
            fi
        fi
    else
        echo -e "${RED}  Backup failed - aborting deployment${NC}"
        echo "Run with --skip-backup to bypass (NOT recommended)"
        exit 1
    fi
elif [ "$SKIP_BACKUP" = true ]; then
    echo ""
    echo -e "${YELLOW}Skipping database backup (--skip-backup)${NC}"
    echo -e "${RED}  WARNING: No backup created before deployment${NC}"
elif [ "$DRY_RUN" = true ]; then
    echo ""
    echo -e "${BLUE}[DRY-RUN] Would create database backup${NC}"
fi

# ==============================================================================
# START/UPDATE INFRASTRUCTURE (Docker)
# ==============================================================================

echo ""
echo -e "${YELLOW}Starting infrastructure (Docker)...${NC}"

if [ "$DRY_RUN" = true ]; then
    echo -e "${BLUE}[DRY-RUN] Would run: docker compose -f ${COMPOSE_FILE} up -d${NC}"
else
    ssh ${REMOTE_SERVER} "cd ${REMOTE_PATH} && docker compose -f ${COMPOSE_FILE} up -d"

    # Wait for infrastructure to be healthy
    echo -e "${BLUE}  Waiting for infrastructure to be ready...${NC}"
    TIMEOUT=30
    ELAPSED=0
    while [ $ELAPSED -lt $TIMEOUT ]; do
        DB_READY=$(ssh ${REMOTE_SERVER} "docker exec family_app_db pg_isready -U familyapp 2>/dev/null && echo 'ok'" || echo "")
        if [ "$DB_READY" = "ok" ]; then
            break
        fi
        sleep 2
        ELAPSED=$((ELAPSED + 2))
        echo -n "."
    done
    echo ""

    if [ "$DB_READY" = "ok" ]; then
        echo -e "${GREEN}  Infrastructure is ready${NC}"
    else
        echo -e "${YELLOW}  Infrastructure may still be starting (continuing anyway)${NC}"
    fi
fi

# ==============================================================================
# DATABASE MIGRATIONS
# ==============================================================================

if [ "$SKIP_MIGRATIONS" = false ]; then
    echo ""
    echo -e "${YELLOW}Running database migrations...${NC}"

    if [ "$DRY_RUN" = true ]; then
        echo -e "${BLUE}[DRY-RUN] Would run: alembic upgrade head${NC}"
    else
        # Check current migration
        echo -e "${BLUE}  Checking current migration status...${NC}"
        CURRENT_MIGRATION=$(ssh ${REMOTE_SERVER} "cd ${REMOTE_PATH}/backend && ${REMOTE_PATH}/venv/bin/python3 -m alembic current 2>&1 | grep -v 'INFO'" || echo "Unknown")
        echo -e "${BLUE}  Current: ${CURRENT_MIGRATION}${NC}"

        # Run migrations
        ssh ${REMOTE_SERVER} "cd ${REMOTE_PATH}/backend && ${REMOTE_PATH}/venv/bin/python3 -m alembic upgrade head"

        if [ $? -eq 0 ]; then
            NEW_MIGRATION=$(ssh ${REMOTE_SERVER} "cd ${REMOTE_PATH}/backend && ${REMOTE_PATH}/venv/bin/python3 -m alembic current 2>&1 | grep -v 'INFO'" || echo "Unknown")
            echo -e "${GREEN}  Migrations completed${NC}"
            if [ "$CURRENT_MIGRATION" != "$NEW_MIGRATION" ]; then
                echo -e "${GREEN}  Database schema updated: ${NEW_MIGRATION}${NC}"
            else
                echo -e "${BLUE}  Already up to date${NC}"
            fi
        else
            echo -e "${RED}  Migration failed${NC}"
            exit 1
        fi
    fi
else
    echo ""
    echo -e "${YELLOW}Skipping database migrations (--skip-migrations)${NC}"
    echo -e "${RED}  WARNING: Database schema may be out of date${NC}"
fi

# ==============================================================================
# INSTALL DEPENDENCIES & BUILD
# ==============================================================================

if [ "$SKIP_BUILD" = false ]; then
    echo ""
    echo -e "${YELLOW}Installing dependencies and building...${NC}"

    if [ "$DRY_RUN" = true ]; then
        echo -e "${BLUE}[DRY-RUN] Would install Python deps: pip install -r requirements.txt${NC}"
        echo -e "${BLUE}[DRY-RUN] Would install Node deps: npm ci${NC}"
        echo -e "${BLUE}[DRY-RUN] Would build frontend: npm run build${NC}"
    else
        # Python dependencies (backend)
        echo -e "${BLUE}  Installing Python dependencies (backend)...${NC}"
        ssh ${REMOTE_SERVER} "cd ${REMOTE_PATH} && ${REMOTE_PATH}/venv/bin/pip install -r backend/requirements.txt -q"
        echo -e "${GREEN}  Backend Python deps installed${NC}"

        # Python dependencies (finance API)
        echo -e "${BLUE}  Installing Python dependencies (finance API)...${NC}"
        ssh ${REMOTE_SERVER} "cd ${REMOTE_PATH} && ${REMOTE_PATH}/venv/bin/pip install -r services/actual-budget/requirements.txt -q"
        echo -e "${GREEN}  Finance API Python deps installed${NC}"

        # Node.js dependencies (frontend)
        echo -e "${BLUE}  Installing Node.js dependencies (frontend)...${NC}"
        if [ "$QUICK_MODE" = true ]; then
            ssh ${REMOTE_SERVER} "cd ${REMOTE_PATH}/frontend && npm install --prefer-offline"
        else
            ssh ${REMOTE_SERVER} "cd ${REMOTE_PATH}/frontend && npm ci"
        fi
        echo -e "${GREEN}  Frontend Node.js deps installed${NC}"

        # Build Astro frontend
        echo -e "${BLUE}  Building Astro frontend...${NC}"
        ssh ${REMOTE_SERVER} "cd ${REMOTE_PATH}/frontend && npm run build"
        echo -e "${GREEN}  Frontend build completed${NC}"
    fi
else
    echo ""
    echo -e "${YELLOW}Skipping build (--skip-build)${NC}"
fi

# ==============================================================================
# RESTART PM2 APPLICATIONS
# ==============================================================================

echo ""
echo -e "${YELLOW}Restarting PM2 applications...${NC}"

if [ "$DRY_RUN" = true ]; then
    echo -e "${BLUE}[DRY-RUN] Would stop existing PM2 apps: ${PM2_APPS}${NC}"
    echo -e "${BLUE}[DRY-RUN] Would start: pm2 start ecosystem.config.cjs --env ${PM2_ENV}${NC}"
else
    # Create logs directory
    ssh ${REMOTE_SERVER} "mkdir -p ${REMOTE_PATH}/logs"

    # Load environment variables and restart PM2
    echo -e "${BLUE}  Stopping existing PM2 apps...${NC}"
    ssh ${REMOTE_SERVER} "pm2 delete ${PM2_APPS} 2>/dev/null || true"

    echo -e "${BLUE}  Starting PM2 apps (env: ${PM2_ENV})...${NC}"
    ssh ${REMOTE_SERVER} "cd ${REMOTE_PATH} && export \$(grep -v '^#' .env 2>/dev/null | xargs) && pm2 start ecosystem.config.cjs --env ${PM2_ENV} && pm2 save"

    echo -e "${GREEN}  PM2 applications started${NC}"
fi

# ==============================================================================
# HEALTH CHECKS
# ==============================================================================

echo ""
echo -e "${YELLOW}Running health checks...${NC}"

if [ "$DRY_RUN" = true ]; then
    echo -e "${BLUE}[DRY-RUN] Would check: http://localhost:${BACKEND_PORT}/health${NC}"
    echo -e "${BLUE}[DRY-RUN] Would check: http://localhost:${FRONTEND_PORT}${NC}"
else
    # Wait for apps to start
    sleep 5

    # Backend health check
    TIMEOUT=60
    ELAPSED=0
    BACKEND_HEALTHY=false

    echo -n "  Backend"
    while [ $ELAPSED -lt $TIMEOUT ]; do
        if ssh ${REMOTE_SERVER} "curl -sf http://localhost:${BACKEND_PORT}/health" > /dev/null 2>&1; then
            BACKEND_HEALTHY=true
            break
        fi
        sleep 2
        ELAPSED=$((ELAPSED + 2))
        echo -n "."
    done
    echo ""

    if [ "$BACKEND_HEALTHY" = true ]; then
        echo -e "${GREEN}  Backend is healthy (port ${BACKEND_PORT})${NC}"
    else
        echo -e "${RED}  Backend health check failed after ${TIMEOUT}s${NC}"
        echo -e "${YELLOW}  Checking PM2 logs:${NC}"
        ssh ${REMOTE_SERVER} "pm2 logs family-backend --lines 20 --nostream" 2>/dev/null || true
    fi

    # Frontend health check
    ELAPSED=0
    FRONTEND_HEALTHY=false

    echo -n "  Frontend"
    while [ $ELAPSED -lt 30 ]; do
        if ssh ${REMOTE_SERVER} "curl -sf http://localhost:${FRONTEND_PORT}" > /dev/null 2>&1; then
            FRONTEND_HEALTHY=true
            break
        fi
        sleep 2
        ELAPSED=$((ELAPSED + 2))
        echo -n "."
    done
    echo ""

    if [ "$FRONTEND_HEALTHY" = true ]; then
        echo -e "${GREEN}  Frontend is healthy (port ${FRONTEND_PORT})${NC}"
    else
        echo -e "${RED}  Frontend health check failed${NC}"
        echo -e "${YELLOW}  Checking PM2 logs:${NC}"
        ssh ${REMOTE_SERVER} "pm2 logs family-frontend --lines 20 --nostream" 2>/dev/null || true
    fi

    # Finance API health check (non-blocking)
    if ssh ${REMOTE_SERVER} "curl -sf http://localhost:${FINANCE_API_PORT}/health" > /dev/null 2>&1; then
        echo -e "${GREEN}  Finance API is healthy (port ${FINANCE_API_PORT})${NC}"
    else
        echo -e "${YELLOW}  Finance API not responding (may need configuration)${NC}"
    fi

    # Overall result
    if [ "$BACKEND_HEALTHY" = true ] && [ "$FRONTEND_HEALTHY" = true ]; then
        echo ""
        echo -e "${GREEN}All core services are healthy!${NC}"
    else
        echo ""
        echo -e "${RED}Some services failed health checks. Check logs above.${NC}"
        exit 1
    fi
fi

# ==============================================================================
# DEPLOYMENT SUMMARY
# ==============================================================================

echo ""
if [ "$DRY_RUN" = true ]; then
    echo -e "${GREEN}[DRY-RUN] Deployment preview completed!${NC}"
    echo "========================================"
    echo ""
    echo -e "${BLUE}What would be deployed:${NC}"
    echo "   Branch:      ${REMOTE_BRANCH}"
    echo "   Target:      ${REMOTE_SERVER}:${REMOTE_PATH}"
    echo "   Infra:       ${COMPOSE_FILE} (Docker)"
    echo "   Apps:        PM2 --env ${PM2_ENV}"
    [ "$SKIP_BUILD" = false ] && echo "   Build:       Yes" || echo "   Build:       Skipped"
    [ "$SKIP_BACKUP" = false ] && echo "   Backup:      Yes" || echo "   Backup:      Skipped"
    [ "$SKIP_MIGRATIONS" = false ] && echo "   Migrations:  Yes" || echo "   Migrations:  Skipped"
    echo ""
    echo -e "${YELLOW}Run without --dry-run to perform actual deployment${NC}"
    exit 0
fi

echo -e "${GREEN}Deployment completed successfully!${NC}"
echo "========================================"
echo ""

echo -e "${BLUE}Application URLs:${NC}"
echo "   Frontend:    ${BASE_URL}"
echo "   Backend API: http://${REMOTE_HOST}:${BACKEND_PORT}"
echo "   API Docs:    http://${REMOTE_HOST}:${BACKEND_PORT}/docs"
echo "   Health:      http://${REMOTE_HOST}:${BACKEND_PORT}/health"
echo "   Actual:      http://${REMOTE_HOST}:${ACTUAL_BUDGET_PORT}"
echo ""

echo -e "${BLUE}Infrastructure (Docker):${NC}"
echo "   PostgreSQL:     family_app_db (port ${DB_PORT})"
echo "   Redis:          family_app_redis (port ${REDIS_PORT})"
echo "   Actual Budget:  family_actual_budget (port ${ACTUAL_BUDGET_PORT})"
echo ""

echo -e "${BLUE}Applications (PM2):${NC}"
ssh ${REMOTE_SERVER} "pm2 list" 2>/dev/null || echo "   (unable to retrieve PM2 status)"
echo ""

if [ "$SKIP_BACKUP" = false ]; then
    echo -e "${BLUE}Backup Information:${NC}"
    echo "   Backup: backups/pre-deploy-${BACKUP_TIMESTAMP}"
    echo "   Restore: ssh ${REMOTE_SERVER} 'cd ${REMOTE_PATH} && gunzip -c ${BACKUP_DIR}/*.sql.gz | docker exec -i family_app_db psql -U familyapp familyapp'"
    echo ""
fi

echo -e "${BLUE}Useful Commands:${NC}"
echo "   PM2 status:  ssh ${REMOTE_SERVER} 'pm2 list'"
echo "   PM2 logs:    ssh ${REMOTE_SERVER} 'pm2 logs --lines 50'"
echo "   Restart all: ssh ${REMOTE_SERVER} 'cd ${REMOTE_PATH} && pm2 reload ecosystem.config.cjs --env ${PM2_ENV}'"
echo "   Infra logs:  ssh ${REMOTE_SERVER} 'cd ${REMOTE_PATH} && docker compose -f ${COMPOSE_FILE} logs -f'"
echo "   SSH:         ssh ${REMOTE_SERVER}"
echo ""
