# Family Task Manager - Deployment Guide

**Version**: 1.0.0  
**Last Updated**: January 25, 2026  
**Maintainer**: AgentIA Team

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Prerequisites](#prerequisites)
4. [Vault Setup](#vault-setup)
5. [Deployment Environments](#deployment-environments)
6. [Deployment Commands](#deployment-commands)
7. [Server Configuration](#server-configuration)
8. [Troubleshooting](#troubleshooting)
9. [Rollback Procedures](#rollback-procedures)

---

## Overview

The Family Task Manager uses a **git-based deployment workflow** with:

- **HashiCorp Vault** for secrets management
- **Docker Compose** for infrastructure services (PostgreSQL, Redis)
- **PM2** for application process management (Python/Uvicorn)
- **OpenCode `/deploy` command** for automated deployments

### Deployment Flow

```
Local Development          Staging/Production
─────────────────         ───────────────────
1. Make changes           1. /deploy stage
2. Commit & push    →     2. Pull on server
3. /deploy dev            3. Docker containers up
                          4. Run migrations
                          5. PM2 restart apps
                          6. Health checks
```

---

## Architecture

### Service Overview

```
┌─────────────────────────────────────────────────────────────┐
│                        NGINX (Reverse Proxy)                 │
│                    (External - Port 80/443)                  │
└─────────────────────┬───────────────────┬───────────────────┘
                      │                   │
         ┌────────────┴─────┐    ┌───────┴────────────┐
         │  Frontend (PM2)  │    │   Backend (PM2)    │
         │  Python/Uvicorn  │    │   Python/Uvicorn   │
         │    Port 3000     │    │     Port 8000      │
         └────────────────┬─┘    └─┬──────────────────┘
                          │        │
         ┌────────────────┴────────┴──────────────────┐
         │              Docker Compose                 │
         │  ┌─────────────┐    ┌─────────────────┐   │
         │  │ PostgreSQL  │    │      Redis      │   │
         │  │  Port 5433  │    │    Port 6380    │   │
         │  └─────────────┘    └─────────────────┘   │
         └─────────────────────────────────────────────┘
```

### Port Mapping

| Service    | Dev Port | Stage Port | Prod Port |
|------------|----------|------------|-----------|
| Frontend   | 3000     | 3000       | 3000      |
| Backend    | 8000     | 8000       | 8000      |
| PostgreSQL | 5433     | 5433       | 5433      |
| Redis      | 6380     | 6380       | 6380      |

---

## Prerequisites

### Local Machine

```bash
# Required tools
brew install vault           # HashiCorp Vault CLI
brew install jq              # JSON processor
brew install docker          # Docker Desktop

# Optional but recommended
brew install pm2             # For testing PM2 configs locally
```

### Remote Servers (Stage/Prod)

```bash
# Install on Ubuntu/Debian
sudo apt update
sudo apt install -y docker.io docker-compose python3.12 python3.12-venv

# Install PM2
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
sudo npm install -g pm2

# Install Vault CLI
wget -O- https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/hashicorp.list
sudo apt update && sudo apt install vault
```

---

## Vault Setup

### Initial Configuration

1. **Authenticate with Vault:**

```bash
# Set Vault address (if not already configured)
export VAULT_ADDR="https://vault.a-ai4all.com:8200"

# Login (use your preferred method)
vault login
```

2. **Run the setup script:**

```bash
# This creates secrets for all environments
./scripts/setup-vault.sh
```

3. **Update secrets with real values:**

```bash
# Update staging secrets
vault kv patch secret/family-task-manager/stage \
    DATABASE_URL="postgresql+asyncpg://familyapp:REAL_PASSWORD@localhost:5433/familyapp" \
    GOOGLE_CLIENT_ID="your-google-client-id" \
    GOOGLE_CLIENT_SECRET="your-google-client-secret"

# Update production secrets
vault kv patch secret/family-task-manager/prod \
    DATABASE_URL="postgresql+asyncpg://familyapp:PROD_PASSWORD@localhost:5433/familyapp" \
    GOOGLE_CLIENT_ID="your-prod-google-client-id" \
    GOOGLE_CLIENT_SECRET="your-prod-google-client-secret"
```

### Vault Secret Structure

```
secret/family-task-manager/
├── dev/
│   ├── DATABASE_URL
│   ├── SECRET_KEY
│   ├── JWT_SECRET_KEY
│   ├── DEBUG
│   ├── BASE_URL
│   ├── REDIS_URL
│   ├── ALLOWED_ORIGINS
│   ├── GOOGLE_CLIENT_ID
│   ├── GOOGLE_CLIENT_SECRET
│   ├── GOOGLE_REDIRECT_URI
│   ├── SMTP_HOST
│   ├── SMTP_PORT
│   ├── SMTP_USER
│   ├── SMTP_PASSWORD
│   ├── SMTP_FROM_EMAIL
│   ├── SMTP_FROM_NAME
│   └── LOG_LEVEL
├── stage/
│   └── (same structure)
└── prod/
    └── (same structure)
```

### Viewing Secrets

```bash
# List all secrets
vault kv list secret/family-task-manager/

# View specific environment
vault kv get secret/family-task-manager/dev

# View specific field
vault kv get -field=DATABASE_URL secret/family-task-manager/stage
```

### Updating Secrets

```bash
# Update single field
vault kv patch secret/family-task-manager/stage SMTP_PASSWORD="new-password"

# Update multiple fields
vault kv patch secret/family-task-manager/prod \
    GOOGLE_CLIENT_ID="new-id" \
    GOOGLE_CLIENT_SECRET="new-secret"
```

---

## Deployment Environments

### Development (Local)

**Purpose**: Local development and testing

```bash
# Start local environment
/deploy dev

# Or manually:
docker-compose up -d
./scripts/download-config.sh dev
```

**URLs:**
- Frontend: http://localhost:3000
- Backend: http://localhost:8000
- API Docs: http://localhost:8000/docs

### Staging

**Purpose**: Pre-production testing, QA validation

**Server**: `jc@10.1.0.91`  
**Path**: `/home/jc/family-task-manager`

```bash
# Deploy to staging (any branch allowed)
/deploy stage
```

**URLs:**
- Frontend: https://fam-stage.a-ai4all.com
- Backend: https://fam-stage.a-ai4all.com/api
- API Docs: https://fam-stage.a-ai4all.com/api/docs

### Production

**Purpose**: Live user-facing environment

**Server**: `jc@10.1.0.92`  
**Path**: `/home/jc/family-task-manager`

```bash
# Deploy to production (main/master branch only)
/deploy prod
```

**URLs:**
- Frontend: https://fam.a-ai4all.com
- Backend: https://fam.a-ai4all.com/api
- API Docs: https://fam.a-ai4all.com/api/docs

---

## Deployment Commands

### Using OpenCode `/deploy` Command

The `/deploy` command automates the entire deployment workflow:

```bash
# Local development
/deploy dev

# Staging (any branch)
/deploy stage

# Production (main/master only, requires confirmation)
/deploy prod
```

### Manual Deployment

If you need to deploy manually:

```bash
# 1. Download config from Vault
./scripts/download-config.sh stage

# 2. Copy config to server
scp .env jc@10.1.0.91:/home/jc/family-task-manager/.env

# 3. SSH to server
ssh jc@10.1.0.91

# 4. Pull latest code
cd /home/jc/family-task-manager
git pull origin main

# 5. Start Docker containers
docker compose -f docker-compose.stage.yml up -d

# 6. Wait for containers
sleep 15

# 7. Run migrations
docker exec family_app_backend alembic upgrade head

# 8. Restart PM2 apps
export $(grep -v '^#' .env | xargs)
pm2 delete family-backend family-frontend 2>/dev/null || true
pm2 start ecosystem.config.cjs --env stage
pm2 save

# 9. Restore local dev config
./scripts/download-config.sh dev
```

---

## Server Configuration

### Initial Server Setup

Run these commands on a new server:

```bash
# 1. Create project directory
mkdir -p /home/jc/family-task-manager
cd /home/jc/family-task-manager

# 2. Clone repository
git clone git@github.com:staff-ai-0/family-task-manager.git .

# 3. Create Python virtual environment
python3.12 -m venv venv
source venv/bin/activate

# 4. Install Python dependencies
pip install -r backend/requirements.txt
pip install -r frontend/requirements.txt

# 5. Create logs directory
mkdir -p logs

# 6. Start Docker containers
docker compose -f docker-compose.stage.yml up -d

# 7. Setup PM2
pm2 start ecosystem.config.cjs --env stage
pm2 save
pm2 startup  # Follow instructions to enable auto-start
```

### NGINX Configuration

Example NGINX config for staging:

```nginx
# /etc/nginx/sites-available/fam-stage.a-ai4all.com

upstream family_frontend {
    server 127.0.0.1:3000;
}

upstream family_backend {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name fam-stage.a-ai4all.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name fam-stage.a-ai4all.com;

    ssl_certificate /etc/letsencrypt/live/fam-stage.a-ai4all.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/fam-stage.a-ai4all.com/privkey.pem;

    # Frontend
    location / {
        proxy_pass http://family_frontend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
    }

    # Backend API
    location /api {
        rewrite ^/api(.*)$ $1 break;
        proxy_pass http://family_backend;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

## Troubleshooting

### Common Issues

#### 1. Vault Authentication Failed

```
Error: Not authenticated with Vault.
```

**Solution:**
```bash
vault login
# Or check token expiry
vault token lookup
```

#### 2. SSH Connection Failed

```
Error: Cannot connect to stage server: jc@10.1.0.91
```

**Solution:**
```bash
# Check SSH key
ssh-add -l

# Add key if missing
ssh-add ~/.ssh/id_rsa

# Test connection
ssh -v jc@10.1.0.91
```

#### 3. Docker Container Won't Start

```bash
# Check container logs
ssh jc@10.1.0.91 "cd /home/jc/family-task-manager && docker compose logs db"

# Check port conflicts
ssh jc@10.1.0.91 "lsof -i :5433"
```

#### 4. PM2 App Crashes

```bash
# Check PM2 logs
ssh jc@10.1.0.91 "pm2 logs family-backend --lines 100"

# Check environment variables
ssh jc@10.1.0.91 "pm2 env family-backend"

# Restart with fresh env
ssh jc@10.1.0.91 "cd /home/jc/family-task-manager && export \$(grep -v '^#' .env | xargs) && pm2 restart family-backend"
```

#### 5. Database Migration Failed

```bash
# Check migration status
ssh jc@10.1.0.91 "docker exec family_app_backend alembic current"

# View migration history
ssh jc@10.1.0.91 "docker exec family_app_backend alembic history"

# Manually run migration
ssh jc@10.1.0.91 "docker exec family_app_backend alembic upgrade head"
```

### Health Check Commands

```bash
# Check all services
ssh jc@10.1.0.91 "pm2 status && docker compose ps"

# Test API
ssh jc@10.1.0.91 "curl -s http://localhost:8000/docs | head -20"

# Test Frontend
ssh jc@10.1.0.91 "curl -s -o /dev/null -w '%{http_code}' http://localhost:3000/"

# Check database connection
ssh jc@10.1.0.91 "docker exec family_app_db psql -U familyapp -c '\dt'"
```

---

## Rollback Procedures

### Quick Rollback

```bash
# SSH to server
ssh jc@10.1.0.91
cd /home/jc/family-task-manager

# Revert to previous commit
git log --oneline -5  # Find commit to rollback to
git checkout <commit-sha>

# Restart services
pm2 restart all
```

### Full Rollback with Database

```bash
# 1. Stop applications
pm2 stop all

# 2. Revert code
git checkout <commit-sha>

# 3. Rollback database migration
docker exec family_app_backend alembic downgrade -1

# 4. Restart applications
pm2 start all
```

### Emergency: Restore from Backup

```bash
# 1. Stop all services
pm2 stop all
docker compose down

# 2. Restore database
docker exec -i family_app_db psql -U familyapp < /backups/postgres/backup.sql

# 3. Restart services
docker compose up -d
sleep 15
pm2 start all
```

---

## File Reference

| File | Purpose |
|------|---------|
| `scripts/deploy.sh` | Main deployment script with server config |
| `scripts/download-config.sh` | Downloads secrets from Vault |
| `scripts/setup-vault.sh` | Initial Vault secrets setup |
| `ecosystem.config.cjs` | PM2 process configuration |
| `docker-compose.yml` | Local development (full stack) |
| `docker-compose.stage.yml` | Staging (infrastructure only) |
| `docker-compose.prod.yml` | Production (infrastructure only) |

---

## Security Notes

1. **Never commit `.env` files** - They contain secrets
2. **Rotate secrets regularly** - Use `vault kv patch` to update
3. **Use unique secrets per environment** - Don't share between dev/stage/prod
4. **Audit Vault access** - `vault audit list`
5. **Backup before deployments** - Especially for production

---

## Support

- **Issues**: https://github.com/staff-ai-0/family-task-manager/issues
- **Vault Dashboard**: https://vault.a-ai4all.com
- **PM2 Dashboard**: `pm2 monit` (on server)
