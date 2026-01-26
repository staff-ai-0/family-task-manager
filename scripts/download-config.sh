#!/bin/bash
#
# Family Task Manager - Vault Configuration Download Script
# ==========================================================
# Downloads environment configuration from HashiCorp Vault.
#
# Prerequisites:
#   - Vault CLI installed (brew install vault)
#   - Vault authenticated (vault login)
#   - Access to secret/family-task-manager/{env}
#
# Usage:
#   ./scripts/download-config.sh [dev|stage|prod]
#
# Vault Paths:
#   - secret/family-task-manager/dev
#   - secret/family-task-manager/stage
#   - secret/family-task-manager/prod
#

set -e

# ==============================================================================
# CONFIGURATION
# ==============================================================================

VAULT_PATH_PREFIX="secret/family-task-manager"
OUTPUT_FILE=".env"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

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
# VALIDATION
# ==============================================================================

ENV=${1:-dev}

case $ENV in
    dev|stage|prod)
        ;;
    *)
        log_error "Unknown environment: $ENV"
        echo "Usage: $0 [dev|stage|prod]"
        exit 1
        ;;
esac

# Check Vault CLI
if ! command -v vault &> /dev/null; then
    log_error "Vault CLI not installed."
    echo ""
    echo "Install with:"
    echo "  brew install vault"
    exit 1
fi

# Check Vault authentication
if ! vault token lookup > /dev/null 2>&1; then
    log_error "Not authenticated with Vault."
    echo ""
    echo "Authenticate with:"
    echo "  vault login"
    exit 1
fi

# ==============================================================================
# DOWNLOAD CONFIGURATION
# ==============================================================================

VAULT_PATH="${VAULT_PATH_PREFIX}/${ENV}"
log_info "Downloading configuration from: $VAULT_PATH"

# Get secrets from Vault and convert to .env format
# Vault KV v2 returns data in .data.data path
SECRETS=$(vault kv get -format=json "$VAULT_PATH" 2>/dev/null)

if [ $? -ne 0 ] || [ -z "$SECRETS" ]; then
    log_error "Failed to retrieve secrets from $VAULT_PATH"
    echo ""
    echo "Make sure the secret exists. Create it with:"
    echo "  vault kv put $VAULT_PATH \\"
    echo "    DATABASE_URL=\"postgresql+asyncpg://user:pass@host:5432/db\" \\"
    echo "    SECRET_KEY=\"your-secret-key\" \\"
    echo "    ..."
    exit 1
fi

# Parse JSON and create .env file
# Handle both KV v1 and v2 formats
if echo "$SECRETS" | jq -e '.data.data' > /dev/null 2>&1; then
    # KV v2
    DATA_PATH='.data.data'
else
    # KV v1
    DATA_PATH='.data'
fi

echo "$SECRETS" | jq -r "$DATA_PATH | to_entries | .[] | \"\(.key)=\\\"\(.value)\\\"\"" > "$OUTPUT_FILE"

if [ ! -s "$OUTPUT_FILE" ]; then
    log_error "Failed to parse secrets. Output file is empty."
    exit 1
fi

# Add header comment
TEMP_FILE=$(mktemp)
cat > "$TEMP_FILE" << EOF
# Family Task Manager - Environment Configuration
# ================================================
# Generated from Vault: $VAULT_PATH
# Generated at: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# Environment: $ENV
#
# DO NOT COMMIT THIS FILE TO VERSION CONTROL
#

EOF

cat "$OUTPUT_FILE" >> "$TEMP_FILE"
mv "$TEMP_FILE" "$OUTPUT_FILE"

# Count variables
VAR_COUNT=$(grep -c "=" "$OUTPUT_FILE" || echo "0")
log_info "Downloaded $VAR_COUNT environment variables to $OUTPUT_FILE"

# ==============================================================================
# VALIDATION
# ==============================================================================

log_info "Validating required variables..."

REQUIRED_VARS=(
    "DATABASE_URL"
    "SECRET_KEY"
)

OPTIONAL_VARS=(
    "JWT_SECRET_KEY"
    "GOOGLE_CLIENT_ID"
    "GOOGLE_CLIENT_SECRET"
    "SMTP_HOST"
    "SMTP_USER"
    "SMTP_PASSWORD"
    "REDIS_URL"
)

MISSING=0
for var in "${REQUIRED_VARS[@]}"; do
    if ! grep -q "^${var}=" "$OUTPUT_FILE"; then
        log_error "Missing required variable: $var"
        MISSING=$((MISSING + 1))
    fi
done

if [ $MISSING -gt 0 ]; then
    log_error "$MISSING required variables are missing!"
    exit 1
fi

for var in "${OPTIONAL_VARS[@]}"; do
    if ! grep -q "^${var}=" "$OUTPUT_FILE"; then
        log_warn "Missing optional variable: $var"
    fi
done

log_info "Configuration download complete!"
echo ""
echo "Environment: $ENV"
echo "Output file: $OUTPUT_FILE"
echo "Variables:   $VAR_COUNT"
