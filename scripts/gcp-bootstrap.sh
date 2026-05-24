#!/bin/bash
# ================================
# GCP VM Bootstrap — first-time setup (Family Task Manager)
# ================================
# Run once after the VM is created. Installs docker + docker-compose v2,
# creates the app directory, enables docker-on-boot.
#
# Run from local mac:
#   ./scripts/gcp-bootstrap.sh
#
# Or directly on the VM:
#   bash gcp-bootstrap.sh --run-on-vm
# ================================

set -e
set -o pipefail

GCP_ACCOUNT="${GCP_ACCOUNT:-info@agent-ia.mx}"
GCP_PROJECT="${GCP_PROJECT:-urologos}"
GCP_ZONE="${GCP_ZONE:-us-central1-a}"
GCP_VM="${GCP_VM:-agentia-family-hub}"
REMOTE_USER="${REMOTE_USER:-jc}"
REMOTE_PATH="${REMOTE_PATH:-/home/jc/family-task-manager}"

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'

# If we're on the VM itself, run the install directly.
if [[ "$1" == "--run-on-vm" ]]; then
    set -x
    sudo apt-get update -y
    sudo apt-get install -y ca-certificates curl gnupg lsb-release rsync
    sudo install -m 0755 -d /etc/apt/keyrings
    if [[ ! -f /etc/apt/keyrings/docker.gpg ]]; then
        curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
        sudo chmod a+r /etc/apt/keyrings/docker.gpg
    fi
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
        | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
    sudo apt-get update -y
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    sudo systemctl enable --now docker
    sudo usermod -aG docker "$USER" || true
    mkdir -p "$REMOTE_PATH"
    sudo docker --version
    sudo docker compose version
    exit 0
fi

# Otherwise driven from local mac.
echo -e "${CYAN}Bootstrap target: $GCP_VM ($GCP_ZONE / $GCP_PROJECT)${NC}"

TMP_REMOTE=/tmp/gcp-bootstrap.sh
gcloud --account="$GCP_ACCOUNT" --project="$GCP_PROJECT" \
    compute scp --zone="$GCP_ZONE" "$0" "$REMOTE_USER@$GCP_VM:$TMP_REMOTE"

gcloud --account="$GCP_ACCOUNT" --project="$GCP_PROJECT" \
    compute ssh "$REMOTE_USER@$GCP_VM" --zone="$GCP_ZONE" \
    --command="REMOTE_PATH=$REMOTE_PATH bash $TMP_REMOTE --run-on-vm"

echo -e "${GREEN}✅ VM bootstrap complete${NC}"
echo "Next: copy .env to the VM, then run ./scripts/deploy-gcp.sh"
