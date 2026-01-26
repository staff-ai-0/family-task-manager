#!/bin/bash
#
# Family Task Manager - Vault Secrets Setup Script
# =================================================
# Creates the necessary secrets in HashiCorp Vault for all environments.
#
# Prerequisites:
#   - Vault CLI installed
#   - Vault authenticated with admin privileges
#   - KV secrets engine enabled at 'secret/'
#
# Usage:
#   ./scripts/setup-vault.sh
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_section() { echo -e "\n${BLUE}=== $1 ===${NC}\n"; }

# ==============================================================================
# VALIDATION
# ==============================================================================

log_section "Validating Prerequisites"

# Check Vault CLI
if ! command -v vault &> /dev/null; then
    log_error "Vault CLI not installed."
    echo "Install with: brew install vault"
    exit 1
fi
log_info "Vault CLI found"

# Check Vault authentication
if ! vault token lookup > /dev/null 2>&1; then
    log_error "Not authenticated with Vault."
    echo "Run: vault login"
    exit 1
fi
log_info "Vault authentication valid"

# Check KV engine
if ! vault secrets list | grep -q "^secret/"; then
    log_warn "KV secrets engine not found at 'secret/'. Enabling..."
    vault secrets enable -path=secret kv-v2
fi
log_info "KV secrets engine available"

# ==============================================================================
# HELPER FUNCTION
# ==============================================================================

create_secret() {
    local path=$1
    shift
    
    log_info "Creating secret: $path"
    
    # Check if secret already exists
    if vault kv get "$path" > /dev/null 2>&1; then
        log_warn "Secret already exists: $path"
        read -p "Overwrite? (y/N) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            log_info "Skipping $path"
            return
        fi
    fi
    
    vault kv put "$path" "$@"
    log_info "Created: $path"
}

# ==============================================================================
# GENERATE SECRETS
# ==============================================================================

generate_secret() {
    openssl rand -base64 32 | tr -d '\n'
}

log_section "Generating Random Secrets"

DEV_SECRET_KEY=$(generate_secret)
STAGE_SECRET_KEY=$(generate_secret)
PROD_SECRET_KEY=$(generate_secret)

DEV_JWT_SECRET=$(generate_secret)
STAGE_JWT_SECRET=$(generate_secret)
PROD_JWT_SECRET=$(generate_secret)

log_info "Generated unique secrets for each environment"

# ==============================================================================
# CREATE DEVELOPMENT SECRETS
# ==============================================================================

log_section "Creating Development Secrets"

create_secret "secret/family-task-manager/dev" \
    DATABASE_URL="postgresql+asyncpg://familyapp:familyapp123@localhost:5433/familyapp" \
    SECRET_KEY="$DEV_SECRET_KEY" \
    JWT_SECRET_KEY="$DEV_JWT_SECRET" \
    DEBUG="true" \
    BASE_URL="http://localhost:8000" \
    REDIS_URL="redis://localhost:6380/0" \
    ALLOWED_ORIGINS="http://localhost:3000,http://localhost:8000" \
    GOOGLE_CLIENT_ID="" \
    GOOGLE_CLIENT_SECRET="" \
    GOOGLE_REDIRECT_URI="http://localhost:8000/auth/google/callback" \
    SMTP_HOST="smtp.gmail.com" \
    SMTP_PORT="587" \
    SMTP_USER="" \
    SMTP_PASSWORD="" \
    SMTP_FROM_EMAIL="" \
    SMTP_FROM_NAME="Family Task Manager (Dev)" \
    LOG_LEVEL="DEBUG"

# ==============================================================================
# CREATE STAGING SECRETS
# ==============================================================================

log_section "Creating Staging Secrets"

create_secret "secret/family-task-manager/stage" \
    DATABASE_URL="postgresql+asyncpg://familyapp:CHANGE_ME_STAGE_PASSWORD@localhost:5433/familyapp" \
    SECRET_KEY="$STAGE_SECRET_KEY" \
    JWT_SECRET_KEY="$STAGE_JWT_SECRET" \
    DEBUG="false" \
    BASE_URL="https://fam-stage.a-ai4all.com" \
    REDIS_URL="redis://localhost:6380/0" \
    ALLOWED_ORIGINS="https://fam-stage.a-ai4all.com" \
    GOOGLE_CLIENT_ID="CHANGE_ME" \
    GOOGLE_CLIENT_SECRET="CHANGE_ME" \
    GOOGLE_REDIRECT_URI="https://fam-stage.a-ai4all.com/auth/google/callback" \
    SMTP_HOST="smtp.gmail.com" \
    SMTP_PORT="587" \
    SMTP_USER="CHANGE_ME" \
    SMTP_PASSWORD="CHANGE_ME" \
    SMTP_FROM_EMAIL="noreply@a-ai4all.com" \
    SMTP_FROM_NAME="Family Task Manager (Stage)" \
    LOG_LEVEL="INFO"

# ==============================================================================
# CREATE PRODUCTION SECRETS
# ==============================================================================

log_section "Creating Production Secrets"

create_secret "secret/family-task-manager/prod" \
    DATABASE_URL="postgresql+asyncpg://familyapp:CHANGE_ME_PROD_PASSWORD@localhost:5433/familyapp" \
    SECRET_KEY="$PROD_SECRET_KEY" \
    JWT_SECRET_KEY="$PROD_JWT_SECRET" \
    DEBUG="false" \
    BASE_URL="https://fam.a-ai4all.com" \
    REDIS_URL="redis://localhost:6380/0" \
    ALLOWED_ORIGINS="https://fam.a-ai4all.com" \
    GOOGLE_CLIENT_ID="CHANGE_ME" \
    GOOGLE_CLIENT_SECRET="CHANGE_ME" \
    GOOGLE_REDIRECT_URI="https://fam.a-ai4all.com/auth/google/callback" \
    SMTP_HOST="smtp.gmail.com" \
    SMTP_PORT="587" \
    SMTP_USER="CHANGE_ME" \
    SMTP_PASSWORD="CHANGE_ME" \
    SMTP_FROM_EMAIL="noreply@a-ai4all.com" \
    SMTP_FROM_NAME="Family Task Manager" \
    LOG_LEVEL="WARNING"

# ==============================================================================
# SUMMARY
# ==============================================================================

log_section "Setup Complete"

echo "Created Vault secrets:"
echo "  - secret/family-task-manager/dev"
echo "  - secret/family-task-manager/stage"
echo "  - secret/family-task-manager/prod"
echo ""
echo "Next steps:"
echo "  1. Update staging/production secrets with real values:"
echo "     vault kv patch secret/family-task-manager/stage DATABASE_URL=\"...\""
echo ""
echo "  2. Download config for local development:"
echo "     ./scripts/download-config.sh dev"
echo ""
echo "  3. Verify secrets:"
echo "     vault kv get secret/family-task-manager/dev"
