# GCP → on-prem 10.1.0.91 Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Family Task Manager production off the GCP VM onto on-prem host 10.1.0.91 (RHEL 10.2, rootless podman), serving at `https://family.agent-ia.mx`, then decommission the GCP VM.

**Architecture:** New `docker-compose.onprem.yml` (from the GCP compose, minus GCS, rootless-safe) run as user `jc` via `podman compose` — no host ports, container-DNS ingress through a fresh per-stack Cloudflare tunnel. A new `scripts/deploy-onprem.sh` rsyncs over plain SSH and drives rootless podman. Cutover is one-shot: dump GCP DB + uploads, restore into .91, flip the tunnel.

**Tech Stack:** Python/FastAPI, Astro, PostgreSQL 15, Redis 7, rootless podman 5.8.2 + `podman compose`, Cloudflare Tunnel, systemd user units.

## Global Constraints

- **NEVER `sudo podman` on .91** — registers a root healthcheck timer that corrupts jc's rootless overlay storage (global CLAUDE.md Rule 1). All podman commands run rootless as `jc`.
- **Volume UIDs via `podman unshare chown`** (Rule 4): postgres `70:70`, redis `999:1000`, receipt_uploads `1000:1000`.
- **Rule 5 — address DB/redis by unique container name**, never bare `postgres`/`redis` (box has colliding service names in other stacks).
- **Fresh Cloudflare tunnel token** — never reuse a token across hosts (multi-VM CF load-balancing incident).
- **No host-port publishing** — tunnel reaches services by container DNS on the stack's own bridge networks.
- **User-level systemd units** (`~/.config/systemd/user/`, `WantedBy=default.target`), never system units with `User=jc` (Rule 3).
- **Compose project name pinned** to `family-task-manager` (via `-p`) so volume/network names are deterministic: `family-task-manager_{postgres_data,redis_data,receipt_uploads}`.
- **Container names:** `family_onprem_{db,redis,backend,frontend,tunnel}`.
- **Hostnames:** `family.agent-ia.mx` (frontend), `api-family.agent-ia.mx` (backend) — both single-label under `agent-ia.mx` for universal `*.agent-ia.mx` SSL. `api.family.agent-ia.mx` would break the cert.
- **LiteLLM unchanged:** `LITELLM_API_BASE=https://litellm.agent-ia.mx`, `LITELLM_API_KEY` = proxy master key.
- Do not disturb the box's other stacks (school-admin, medical-omnichannel, platform, vault, monitoring).

---

## Phase 1 — Repo changes (local, no host access needed)

### Task 1: Parameterize email footer host

Footer links in transactional emails are hardcoded to `gcp-family.agent-ia.mx` (retired after cutover → dead links). Drive them from `settings.email_link_base`.

**Files:**
- Modify: `backend/app/services/email_service.py` (footer in `_build_html` ~line 215 and `_build_welcome_html` ~line 312)
- Test: `backend/tests/test_email_footer.py` (create)

**Interfaces:**
- Consumes: `settings.email_link_base` (existing property → frontend origin, `str`).
- Produces: both email templates render the footer host from `settings.email_link_base` instead of a literal.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_email_footer.py
from app.core.config import settings
from app.services.email_service import _build_html, _build_welcome_html
from app.models.user import User, UserRole


def test_build_html_footer_uses_email_link_base(monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_URL", "https://family.agent-ia.mx")
    html = _build_html(
        heading="H", body="B", btn_url="https://family.agent-ia.mx/x",
        btn_text="Go", link_label="or", expiry_note="e", ignore_note="i",
    )
    assert "https://family.agent-ia.mx" in html
    assert "gcp-family.agent-ia.mx" not in html


def test_welcome_html_footer_uses_email_link_base(monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_URL", "https://family.agent-ia.mx")
    html = _build_welcome_html(
        variant="parent", lang="en", user_name="A", family_name="F",
        dashboard_url="https://family.agent-ia.mx/dashboard",
        guide_url="https://family.agent-ia.mx/help",
    )
    assert "https://family.agent-ia.mx" in html
    assert "gcp-family.agent-ia.mx" not in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_email_footer.py -v`
Expected: FAIL — footer still contains `gcp-family.agent-ia.mx`.

- [ ] **Step 3: Add a footer helper and use it in both templates**

At module scope in `email_service.py` (near the other helpers), add:

```python
def _footer_host() -> str:
    """Display host + URL for the email footer, from the public frontend origin."""
    from urllib.parse import urlparse
    base = settings.email_link_base
    host = urlparse(base).netloc or base.replace("https://", "").replace("http://", "")
    return base, host
```

In `_build_html`, before the `return f"""...` build the footer and interpolate it. Replace the literal footer line:

```html
  <div class="ftr">&copy; 2026 AgentIA &mdash; Family Task Manager &mdash; <a href="https://gcp-family.agent-ia.mx" style="color:#00D9FF;text-decoration:none">gcp-family.agent-ia.mx</a></div>
```

with:

```html
  <div class="ftr">&copy; 2026 AgentIA &mdash; Family Task Manager &mdash; <a href="{footer_url}" style="color:#00D9FF;text-decoration:none">{footer_host}</a></div>
```

and add `footer_url, footer_host = _footer_host()` immediately before the `return f"""` in both `_build_html` and `_build_welcome_html`. Confirm `from app.core.config import settings` is already imported at the top of the file (it is used elsewhere); if not, add it.

- [ ] **Step 4: Run test to verify it passes**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_email_footer.py -v`
Expected: PASS.

- [ ] **Step 5: Run the invitation email test (guard against regression)**

`backend/tests/test_invitations.py` sets `PUBLIC_URL=https://gcp-family.agent-ia.mx` in its fixtures, so it still passes with the parameterized footer.
Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_invitations.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/email_service.py backend/tests/test_email_footer.py
git commit -m "fix(email): footer host from email_link_base, not hardcoded gcp-family"
```

---

### Task 2: Parameterize the MCP tokens page URL

`frontend/src/pages/parent/settings/mcp-tokens.astro:107` hardcodes `https://api-gcp-family.agent-ia.mx/mcp`. Drive it from the public API base env.

**Files:**
- Modify: `frontend/src/pages/parent/settings/mcp-tokens.astro:107`

**Interfaces:**
- Consumes: `import.meta.env.PUBLIC_API_BASE_URL` (set in compose from `PUBLIC_API_URL`).

- [ ] **Step 1: Read the current line + surrounding frontmatter**

Run: `sed -n '1,20p;100,112p' frontend/src/pages/parent/settings/mcp-tokens.astro`
Confirm whether a frontmatter var already holds the public API base. If not, add in the component frontmatter (top `---` block):

```astro
const mcpBase = import.meta.env.PUBLIC_API_BASE_URL || 'https://api-family.agent-ia.mx';
```

- [ ] **Step 2: Replace the hardcoded URL**

Change:

```astro
<code class="text-sm text-violet-900 break-all">https://api-gcp-family.agent-ia.mx/mcp</code>
```

to:

```astro
<code class="text-sm text-violet-900 break-all">{mcpBase}/mcp</code>
```

- [ ] **Step 3: Build to verify no template error**

Run: `cd frontend && npm run build`
Expected: build completes, no Astro error on that page.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/parent/settings/mcp-tokens.astro
git commit -m "fix(frontend): MCP URL from PUBLIC_API_BASE_URL, not hardcoded gcp host"
```

---

### Task 3: `docker-compose.onprem.yml`

**Files:**
- Create: `docker-compose.onprem.yml`

**Interfaces:**
- Produces: five services `postgres`, `redis`, `backend`, `frontend`, `tunnel` with container names `family_onprem_*`; backend reaches DB/redis by container name.

- [ ] **Step 1: Create the compose file**

```yaml
# ================================
# On-prem (10.1.0.91) Deployment — Family Task Manager
# ================================
# Rootless podman under user jc. Never `sudo podman` (corrupts rootless storage).
# Deterministic project name: pass `-p family-task-manager` on every command.
#
#   podman compose -p family-task-manager --env-file .env -f docker-compose.onprem.yml up -d
#
# Ingress: per-stack Cloudflare tunnel container (fresh token). No host ports.
# AI routes to on-prem LiteLLM at https://litellm.agent-ia.mx.
# DB/redis addressed by UNIQUE container name (global Rule 5 — DNS collision).
# ================================

services:

  postgres:
    image: postgres:15-alpine
    container_name: family_onprem_db
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    networks:
      - backend
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 10s

  redis:
    image: redis:7-alpine
    container_name: family_onprem_redis
    restart: unless-stopped
    command: redis-server --appendonly yes --maxmemory 256mb --maxmemory-policy allkeys-lru
    volumes:
      - redis_data:/data
    networks:
      - backend
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: family_onprem_backend
    restart: unless-stopped
    env_file:
      - .env
    environment:
      DATABASE_URL: postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@family_onprem_db:5432/${POSTGRES_DB}
      REDIS_URL: redis://family_onprem_redis:6379/0
      BASE_URL: ${PUBLIC_API_URL}
      ALLOWED_ORIGINS: ${ALLOWED_ORIGINS}
      LITELLM_API_BASE: ${LITELLM_API_BASE:-https://litellm.agent-ia.mx}
      ENVIRONMENT: production
      DEBUG: "false"
      VAULT_ENABLED: "false"
    volumes:
      - receipt_uploads:/app/uploads
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    networks:
      - backend
      - frontend
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2 --proxy-headers --forwarded-allow-ips="*"
    healthcheck:
      test: ["CMD-SHELL", "python -c 'import urllib.request,sys; sys.exit(0 if urllib.request.urlopen(\"http://localhost:8000/health\", timeout=3).status==200 else 1)'"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s

  frontend:
    build:
      context: .
      dockerfile: frontend/Dockerfile
      args:
        PUBLIC_GOOGLE_CLIENT_ID: ${PUBLIC_GOOGLE_CLIENT_ID:-}
    container_name: family_onprem_frontend
    restart: unless-stopped
    environment:
      API_BASE_URL: http://family_onprem_backend:8000
      PUBLIC_API_BASE_URL: ${PUBLIC_API_URL}
      PORT: 3000
      HOST: 0.0.0.0
      NODE_ENV: production
    depends_on:
      backend:
        condition: service_healthy
    networks:
      - frontend
    healthcheck:
      test: ["CMD", "node", "-e", "require('http').get('http://localhost:3000/', r => process.exit(r.statusCode < 500 ? 0 : 1)).on('error', () => process.exit(1))"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s

  tunnel:
    image: cloudflare/cloudflared@sha256:6d91c121b803126f7a5344005d17a9324788fc09d305b6e2560ec6040a7ae283
    container_name: family_onprem_tunnel
    restart: unless-stopped
    command: tunnel --no-autoupdate run
    environment:
      TUNNEL_TOKEN: ${CLOUDFLARE_TUNNEL_TOKEN}
    depends_on:
      frontend:
        condition: service_healthy
      backend:
        condition: service_healthy
    networks:
      - frontend
      - backend

networks:
  backend:
    driver: bridge
    internal: true
  frontend:
    driver: bridge

volumes:
  postgres_data:
    driver: local
  redis_data:
    driver: local
  receipt_uploads:
    driver: local
```

> Note: `deploy.resources.limits.memory` from the GCP compose is dropped — rootless podman-compose ignores swarm `deploy:` keys. Memory is not capped here (the box has other stacks; monitor rather than swarm-limit).

- [ ] **Step 2: Validate the compose renders**

Run: `podman compose -p family-task-manager --env-file .env.onprem.example -f docker-compose.onprem.yml config >/dev/null && echo OK`
(Run locally; needs Task 4's example env present.) Expected: `OK`, no unresolved-variable errors.

- [ ] **Step 3: Commit**

```bash
git add docker-compose.onprem.yml
git commit -m "feat(deploy): docker-compose.onprem.yml for rootless podman on 10.1.0.91"
```

---

### Task 4: `.env.onprem.example` + `.deploy.onprem.env`

**Files:**
- Create: `.env.onprem.example`
- Create: `.deploy.onprem.env`

- [ ] **Step 1: Create `.env.onprem.example`** (copy of `.env.gcp.example` with the URL + tunnel + storage deltas)

```bash
# =========================================================================
# ON-PREM (10.1.0.91) — .env template (Family Task Manager)
# =========================================================================
# Copy to .env on the host: cp .env.onprem.example .env && nano .env
# Never commit .env. Rootless podman under user jc — never `sudo podman`.
# =========================================================================

ENVIRONMENT=production
DEBUG=false
LOG_LEVEL=INFO
# RATE_LIMIT_STORAGE_URI=redis://family_onprem_redis:6379/1

# ── Database ──────────────────────────────────────────────────────────────
POSTGRES_USER=familyapp
POSTGRES_PASSWORD=CHANGE_ME_strong_random_password
POSTGRES_DB=familyapp

# ── Application secrets ───────────────────────────────────────────────────
SECRET_KEY=CHANGE_ME_openssl_rand_hex_32
JWT_SECRET_KEY=CHANGE_ME_openssl_rand_hex_32
SESSION_SECRET_KEY=CHANGE_ME_openssl_rand_hex_32
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_DAYS=7

# ── Public URLs (Cloudflare Tunnel — on-prem canonical) ───────────────────
PUBLIC_URL=https://family.agent-ia.mx
PUBLIC_API_URL=https://api-family.agent-ia.mx
BASE_URL=https://api-family.agent-ia.mx
ALLOWED_ORIGINS=https://family.agent-ia.mx,https://api-family.agent-ia.mx

# ── Cloudflare Tunnel (FRESH token for the .91 tunnel — never reuse) ───────
CLOUDFLARE_TUNNEL_TOKEN=CHANGE_ME_new_family_onprem_tunnel_token

# ── LiteLLM (on-prem proxy) ───────────────────────────────────────────────
LITELLM_API_BASE=https://litellm.agent-ia.mx
LITELLM_API_KEY=sk-CHANGE_ME_onprem_master_key
LITELLM_MODEL=claude-haiku

ANTHROPIC_API_KEY=

# ── Google OAuth (add https://family.agent-ia.mx to console origins) ──────
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_CLIENT_IDS=
PUBLIC_GOOGLE_CLIENT_ID=

# ── PayPal ────────────────────────────────────────────────────────────────
PAYPAL_CLIENT_ID=
PAYPAL_CLIENT_SECRET=
PAYPAL_MODE=live
PAYPAL_WEBHOOK_ID=
PAYPAL_PLAN_ID_PLUS_MONTHLY=
PAYPAL_PLAN_ID_PLUS_ANNUAL=
PAYPAL_PLAN_ID_PRO_MONTHLY=
PAYPAL_PLAN_ID_PRO_ANNUAL=

# ── Email (SMTP via Workspace App Password) ───────────────────────────────
RESEND_API_KEY=
EMAIL_FROM=info@agent-ia.mx
EMAIL_FROM_NAME=Family Task Manager
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=info@agent-ia.mx
SMTP_PASSWORD=
SMTP_USE_TLS=true

# ── Sentry ────────────────────────────────────────────────────────────────
SENTRY_DSN=
SENTRY_TRACES_SAMPLE_RATE=0.1

# ── Vault (disabled) ──────────────────────────────────────────────────────
VAULT_ENABLED=false
VAULT_ADDR=
VAULT_TOKEN=
```

- [ ] **Step 2: Create `.deploy.onprem.env`**

```bash
# Config for scripts/deploy-onprem.sh (sourced). Plain SSH — no gcloud.
REMOTE_HOST=10.1.0.91
REMOTE_USER=jc
REMOTE_PATH=/home/jc/family-task-manager
COMPOSE_FILE=docker-compose.onprem.yml
COMPOSE_PROJECT=family-task-manager
```

- [ ] **Step 3: Commit** (note: `.deploy.onprem.env` has no secrets, safe to commit; matches `.deploy.gcp.env` precedent)

```bash
git add .env.onprem.example .deploy.onprem.env
git commit -m "feat(deploy): on-prem env template + deploy config"
```

---

### Task 5: Rootless-safe backup/restore + on-prem systemd units

Make the backup/restore scripts runtime-agnostic (`COMPOSE_CMD` override) and add user-level systemd units for .91.

**Files:**
- Modify: `scripts/backup-db.sh:34`, `scripts/restore-db.sh:52` (parameterize the compose command)
- Create: `scripts/systemd/family-onprem-backup.service`
- Create: `scripts/systemd/family-onprem-backup.timer`

- [ ] **Step 1: Parameterize `backup-db.sh`**

Add near the other env defaults (after line 18):

```bash
COMPOSE_CMD="${COMPOSE_CMD:-sudo docker compose}"
```

Change line 34 from `sudo docker compose --env-file .env -f "$COMPOSE_FILE" exec -T postgres \` to:

```bash
$COMPOSE_CMD --env-file .env -f "$COMPOSE_FILE" exec -T postgres \
```

- [ ] **Step 2: Parameterize `restore-db.sh`**

Add after line 16:

```bash
COMPOSE_CMD="${COMPOSE_CMD:-sudo docker compose}"
```

Change line 52 `... | sudo docker compose --env-file .env -f "$COMPOSE_FILE" exec -T postgres \` to:

```bash
"${DECOMP[@]}" | $COMPOSE_CMD --env-file .env -f "$COMPOSE_FILE" exec -T postgres \
```

- [ ] **Step 3: Create the user systemd backup service**

```ini
# scripts/systemd/family-onprem-backup.service
# USER unit — install under ~/.config/systemd/user/ on 10.1.0.91.
# Rootless podman: NO sudo (global Rule 1). Runs as jc.
[Unit]
Description=Family Task Manager (on-prem) — daily PostgreSQL backup

[Service]
Type=oneshot
WorkingDirectory=/home/jc/family-task-manager
Environment=COMPOSE_CMD=podman compose
Environment=COMPOSE_FILE=docker-compose.onprem.yml
ExecStart=/home/jc/family-task-manager/scripts/backup-db.sh
```

- [ ] **Step 4: Create the user systemd backup timer**

```ini
# scripts/systemd/family-onprem-backup.timer
[Unit]
Description=Run the on-prem Family Task Manager DB backup daily

[Timer]
OnCalendar=*-*-* 03:30:00
Persistent=true

[Install]
WantedBy=timers.target
```

- [ ] **Step 5: Shellcheck the scripts**

Run: `shellcheck scripts/backup-db.sh scripts/restore-db.sh`
Expected: no new errors introduced by the `$COMPOSE_CMD` change (SC2086 word-splitting on `$COMPOSE_CMD` is intentional — it must split into `podman compose`; add `# shellcheck disable=SC2086` on those lines if flagged).

- [ ] **Step 6: Commit**

```bash
git add scripts/backup-db.sh scripts/restore-db.sh scripts/systemd/family-onprem-backup.service scripts/systemd/family-onprem-backup.timer
git commit -m "feat(deploy): rootless-safe backup scripts + on-prem user systemd units"
```

---

### Task 6: `scripts/deploy-onprem.sh`

Rsync over plain SSH + rootless `podman compose` build/up + volume chown + alembic + podman-native health poll.

**Files:**
- Create: `scripts/deploy-onprem.sh`

**Interfaces:**
- Consumes: `.deploy.onprem.env` (Task 4), `docker-compose.onprem.yml` (Task 3).
- Produces: a runnable deploy path `./scripts/deploy-onprem.sh [--skip-build] [--skip-migrations] [--skip-backup] [-y]`.

- [ ] **Step 1: Create the script**

```bash
#!/bin/bash
# ================================
# Family Task Manager — on-prem (10.1.0.91) deploy, rootless podman.
# Transport: rsync + ssh (LAN). NEVER sudo podman (Rule 1).
# ================================
set -e
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
[[ -f "$PROJECT_ROOT/.deploy.onprem.env" ]] && source "$PROJECT_ROOT/.deploy.onprem.env"

REMOTE_HOST="${REMOTE_HOST:-10.1.0.91}"
REMOTE_USER="${REMOTE_USER:-jc}"
REMOTE_PATH="${REMOTE_PATH:-/home/jc/family-task-manager}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.onprem.yml}"
COMPOSE_PROJECT="${COMPOSE_PROJECT:-family-task-manager}"
SSH_TARGET="$REMOTE_USER@$REMOTE_HOST"
DC="podman compose -p $COMPOSE_PROJECT --env-file .env -f $COMPOSE_FILE"

SKIP_CONFIRMATION=false; SKIP_BACKUP=false; SKIP_MIGRATIONS=false; SKIP_BUILD=false
while [[ $# -gt 0 ]]; do case $1 in
  -y|--yes) SKIP_CONFIRMATION=true;; --skip-backup) SKIP_BACKUP=true;;
  --skip-migrations) SKIP_MIGRATIONS=true;; --skip-build) SKIP_BUILD=true;;
  *) echo "unknown option: $1"; exit 1;; esac; shift; done

rssh() { ssh -o BatchMode=yes "$SSH_TARGET" "$1"; }
section() { echo; echo "━━━ $* ━━━"; }

# ── Pre-flight ────────────────────────────────────────────────────────────
section "Pre-flight"
[[ -f "$PROJECT_ROOT/$COMPOSE_FILE" ]] || { echo "missing $COMPOSE_FILE"; exit 1; }
rssh 'podman info >/dev/null' || { echo "rootless podman not available for $SSH_TARGET"; exit 1; }
rssh "podman info --format '{{.Store.GraphRoot}}'" | grep -qv '/var/lib/containers' \
  || { echo "REFUSING: podman GraphRoot looks like system storage — check you are rootless jc"; exit 1; }
echo "rootless podman OK on $REMOTE_HOST"

if [[ "$SKIP_CONFIRMATION" != "true" ]]; then
  echo "Deploy to $SSH_TARGET:$REMOTE_PATH ($COMPOSE_FILE)?"
  read -r -p "Type 'DEPLOY' to continue: " R; [[ "$R" == "DEPLOY" ]] || exit 0
fi

# ── Backup (if stack already running) ─────────────────────────────────────
if [[ "$SKIP_BACKUP" != "true" ]]; then
  section "Backup"
  rssh "cd $REMOTE_PATH && if $DC ps postgres 2>/dev/null | grep -q Up; then \
    COMPOSE_CMD='podman compose' COMPOSE_FILE=$COMPOSE_FILE ./scripts/backup-db.sh; \
    else echo 'no running postgres — skipping'; fi"
fi

# ── Sync code ─────────────────────────────────────────────────────────────
section "Sync"
rssh "mkdir -p $REMOTE_PATH"
rsync -avz --delete \
  --exclude='.git/' --exclude='node_modules/' --exclude='__pycache__/' \
  --exclude='*.pyc' --exclude='.venv/' --exclude='venv/' --exclude='dist/' \
  --exclude='.astro/' --exclude='logs/' --exclude='backups/' --exclude='htmlcov/' \
  --exclude='playwright-report/' --exclude='test-results/' --exclude='e2e-tests/' \
  --exclude='.env' --exclude='.env.local' --exclude='.deploy.onprem.env' \
  -e "ssh -o BatchMode=yes" \
  "$PROJECT_ROOT/" "$SSH_TARGET:$REMOTE_PATH/"

# ── Guard: .env must exist ────────────────────────────────────────────────
rssh "[[ -f $REMOTE_PATH/.env ]]" || { echo "❌ .env missing on host — cp .env.onprem.example .env and fill secrets"; exit 1; }

# ── Build ─────────────────────────────────────────────────────────────────
if [[ "$SKIP_BUILD" != "true" ]]; then
  section "Build"
  rssh "cd $REMOTE_PATH && $DC build backend frontend"
fi

# ── Prepare volumes (rootless UID mapping — Rule 4) ───────────────────────
section "Prepare volumes"
rssh "cd $REMOTE_PATH && \
  podman volume create ${COMPOSE_PROJECT}_postgres_data >/dev/null 2>&1 || true; \
  podman volume create ${COMPOSE_PROJECT}_redis_data >/dev/null 2>&1 || true; \
  podman volume create ${COMPOSE_PROJECT}_receipt_uploads >/dev/null 2>&1 || true; \
  podman unshare chown -R 70:70   \$(podman volume inspect ${COMPOSE_PROJECT}_postgres_data --format '{{.Mountpoint}}'); \
  podman unshare chown -R 999:1000 \$(podman volume inspect ${COMPOSE_PROJECT}_redis_data --format '{{.Mountpoint}}'); \
  podman unshare chown -R 1000:1000 \$(podman volume inspect ${COMPOSE_PROJECT}_receipt_uploads --format '{{.Mountpoint}}')"

# ── Migrate against new image (old backend keeps serving) ─────────────────
if [[ "$SKIP_MIGRATIONS" != "true" ]]; then
  section "Migrate"
  rssh "cd $REMOTE_PATH && $DC up -d --no-recreate postgres redis"
  # wait postgres healthy
  rssh "cd $REMOTE_PATH && for i in \$(seq 1 30); do \
    [ \"\$(podman inspect --format '{{.State.Health.Status}}' family_onprem_db 2>/dev/null)\" = healthy ] && break; sleep 2; done"
  rssh "cd $REMOTE_PATH && $DC run --rm -T --no-deps backend alembic upgrade head"
  rssh "cd $REMOTE_PATH && $DC run --rm -T --no-deps backend alembic current"
fi

# ── Start ─────────────────────────────────────────────────────────────────
section "Start"
rssh "cd $REMOTE_PATH && $DC up -d"

section "Health"
for c in family_onprem_db family_onprem_redis family_onprem_backend family_onprem_frontend; do
  rssh "for i in \$(seq 1 40); do \
    s=\$(podman inspect --format '{{.State.Health.Status}}' $c 2>/dev/null); \
    [ \"\$s\" = healthy ] && { echo '$c healthy'; break; }; sleep 3; done; \
    [ \"\$(podman inspect --format '{{.State.Health.Status}}' $c 2>/dev/null)\" = healthy ] || echo '⚠️ $c not healthy'"
done
rssh "cd $REMOTE_PATH && $DC ps"

# ── Verify public (may 000 until tunnel + DNS live) ───────────────────────
section "Verify public"
for url in https://family.agent-ia.mx https://api-family.agent-ia.mx/health; do
  code=$(curl -s -o /dev/null -w '%{http_code}' "$url" 2>/dev/null || echo 000)
  echo "$url → $code"
done
echo "Deploy complete."
```

- [ ] **Step 2: `chmod +x` + shellcheck**

Run: `chmod +x scripts/deploy-onprem.sh && shellcheck scripts/deploy-onprem.sh`
Expected: no errors (heredoc/quoting warnings acceptable; fix any SC2086 that would break `$DC` splitting — `$DC` must word-split, so `# shellcheck disable=SC2086` where needed).

- [ ] **Step 3: Commit**

```bash
git add scripts/deploy-onprem.sh
git commit -m "feat(deploy): scripts/deploy-onprem.sh — rootless podman deploy to 10.1.0.91"
```

---

## Phase 2 — Provision + first deploy (empty stack on .91) — operator-driven

> These tasks run against the live host + Cloudflare. Driven interactively (Claude + Juan), not autonomous subagents. Each ends with an observable check.

### Task 7: Create the Cloudflare tunnel + fill `.env` on .91

- [ ] **Step 1:** Create a **new** named tunnel `family-onprem` in Cloudflare Zero Trust → Networks → Tunnels (docker/cloudflared connector). Attempt via CF API/`cloudflared` if a local API token/cert is available; otherwise Juan creates it and copies the connector token.
- [ ] **Step 2:** Add public hostname routes on that tunnel:
  - `family.agent-ia.mx` → `http://family_onprem_frontend:3000`
  - `api-family.agent-ia.mx` → `http://family_onprem_backend:8000`
  (Container-name service targets, matching the compose. Cloudflare creates the CNAME DNS records automatically.)
- [ ] **Step 3:** On .91: `cp .env.onprem.example .env` (or scp a filled one), set real secrets — reuse GCP values for `POSTGRES_*`, `SECRET_KEY`, `JWT_SECRET_KEY`, `SESSION_SECRET_KEY`, Google, PayPal, SMTP; set `CLOUDFLARE_TUNNEL_TOKEN` to the new tunnel token; set `LITELLM_API_KEY` to the on-prem master key.
- [ ] **Step 4 (verify):** `ssh jc@10.1.0.91 'cd family-task-manager && grep -c CHANGE_ME .env'` → expect `0`.

### Task 8: First deploy (empty DB)

- [ ] **Step 1:** From local: `./scripts/deploy-onprem.sh --skip-backup` (no existing stack → nothing to back up). Type `DEPLOY`.
- [ ] **Step 2 (verify internal):** `ssh jc@10.1.0.91 "podman inspect --format '{{.State.Health.Status}}' family_onprem_backend"` → `healthy`.
- [ ] **Step 3 (verify internal):** `ssh jc@10.1.0.91 'curl -s -o /dev/null -w "%{http_code}" http://localhost:$(podman port family_onprem_backend 2>/dev/null | head -1 | sed "s/.*://")'` — or simpler, exec the healthcheck: `ssh jc@10.1.0.91 "podman exec family_onprem_backend python -c 'import urllib.request;print(urllib.request.urlopen(\"http://localhost:8000/health\").status)'"` → `200`.
- [ ] **Step 4 (verify public):** `curl -s -o /dev/null -w '%{http_code}' https://api-family.agent-ia.mx/health` → `200` (tunnel live). If `000`, wait for DNS/tunnel propagation.

### Task 9: Install boot + backup systemd units on .91

- [ ] **Step 1:** Copy units into the user systemd dir:
```bash
ssh jc@10.1.0.91 'mkdir -p ~/.config/systemd/user && \
  cp ~/family-task-manager/scripts/systemd/family-onprem-backup.service ~/.config/systemd/user/ && \
  cp ~/family-task-manager/scripts/systemd/family-onprem-backup.timer ~/.config/systemd/user/'
```
- [ ] **Step 2:** Install the boot unit (now shipped in-repo at `scripts/systemd/family-task-manager.service` — Type=oneshot, RemainAfterExit=yes, `WantedBy=default.target`): `cp ~/family-task-manager/scripts/systemd/family-task-manager.service ~/.config/systemd/user/`. Enable it (Step 3).
- [ ] **Step 3:** Enable timer + boot unit (rootless, no sudo):
```bash
ssh jc@10.1.0.91 'systemctl --user daemon-reload && \
  systemctl --user enable --now family-onprem-backup.timer && \
  systemctl --user enable family-task-manager.service'
```
- [ ] **Step 4 (verify):** `ssh jc@10.1.0.91 'systemctl --user list-timers family-onprem-backup.timer --no-pager'` shows the timer scheduled; linger already `yes`.

---

## Phase 3 — Cutover (data migration) — operator-driven

### Task 10: Copy GCP data → .91 (pre-stage, no downtime yet)

- [ ] **Step 1:** Dump the GCP DB to local:
```bash
gcloud --account=info@agent-ia.mx --project=family-prod compute ssh family-app --zone=us-central1-a \
  --command='cd /home/jc/family-task-manager && sudo docker compose --env-file .env -f docker-compose.gcp.yml exec -T postgres pg_dump --clean --if-exists -U familyapp familyapp' | gzip > /tmp/family-cutover-pre.sql.gz
```
- [ ] **Step 2:** Copy GCP `receipt_uploads` files to local (relay), then to .91:
```bash
gcloud ... compute ssh family-app --zone=us-central1-a \
  --command='sudo tar -C $(sudo docker volume inspect family-task-manager_receipt_uploads --format "{{.Mountpoint}}") -czf - .' > /tmp/receipts.tgz
scp /tmp/receipts.tgz jc@10.1.0.91:/tmp/
```
- [ ] **Step 3 (verify):** `ls -lh /tmp/family-cutover-pre.sql.gz /tmp/receipts.tgz` non-empty.

### Task 11: Stop GCP writes, final dump, restore into .91

- [ ] **Step 1:** Halt GCP writes: `gcloud ... compute ssh family-app ... --command='cd /home/jc/family-task-manager && sudo docker compose --env-file .env -f docker-compose.gcp.yml stop backend frontend'`.
- [ ] **Step 2:** Final delta dump (repeat Task 10 Step 1 → `/tmp/family-cutover-final.sql.gz`). This is the authoritative copy.
- [ ] **Step 3:** Copy final dump to .91: `scp /tmp/family-cutover-final.sql.gz jc@10.1.0.91:/tmp/`.
- [ ] **Step 4:** Restore into .91 (the restore script drops+recreates via `--clean`):
```bash
ssh jc@10.1.0.91 'cd family-task-manager && \
  COMPOSE_CMD="podman compose" COMPOSE_FILE=docker-compose.onprem.yml \
  ./scripts/restore-db.sh /tmp/family-cutover-final.sql.gz'
```
(Answer the typed `restore` prompt.)
- [ ] **Step 5:** Load receipt files into the .91 volume + fix perms:
```bash
ssh jc@10.1.0.91 'MP=$(podman volume inspect family-task-manager_receipt_uploads --format "{{.Mountpoint}}"); \
  tar -C "$MP" -xzf /tmp/receipts.tgz && podman unshare chown -R 1000:1000 "$MP"'
```
- [ ] **Step 6:** Restart backend to pick up restored data cleanly: `ssh jc@10.1.0.91 'cd family-task-manager && podman compose -p family-task-manager --env-file .env -f docker-compose.onprem.yml restart backend'`.
- [ ] **Step 7 (verify):** `ssh jc@10.1.0.91 'podman exec family_onprem_db psql -U familyapp familyapp -c "select count(*) from users;"'` → matches GCP row count.

### Task 12: Public verification on .91

- [ ] **Step 1:** `curl -sS -o /dev/null -w '%{http_code}\n' https://family.agent-ia.mx` → 200/redirect.
- [ ] **Step 2:** `curl -sS https://api-family.agent-ia.mx/health` → healthy JSON.
- [ ] **Step 3:** Log in as `juan.mtz79@gmail.com` on `https://family.agent-ia.mx`; confirm dashboard + budget data present (restored DB).
- [ ] **Step 4:** Open one gig with a proof image; confirm it renders (volume + perms). Run a receipt scan; confirm the LiteLLM path works from .91.
- [ ] **Step 5 (nav SSR sanity, ported):** `ssh jc@10.1.0.91 "podman exec family_onprem_frontend sh -c 'grep -rl \"href=\\\"/chat\\\"\" /app/dist/server/ | head -1'"` → non-empty.

### Task 13: External touchpoints

- [ ] **Step 1:** Google Cloud console → OAuth client → add `https://family.agent-ia.mx` to Authorized JavaScript origins and `https://api-family.agent-ia.mx/auth/google/callback` to redirect URIs (Juan, or gcloud if scriptable). Verify Google sign-in works on the new origin.
- [ ] **Step 2:** PayPal dashboard → confirm return/webhook URLs don't hardcode `gcp-family`; update to `family.agent-ia.mx` if present. (App builds PayPal return URLs from `PUBLIC_URL`, already set — verify a subscribe flow reaches PayPal and returns.)

---

## Phase 4 — Decommission GCP + docs

### Task 14: Decommission the GCP VM

- [ ] **Step 1:** Stop the GCP tunnel first (prevents CF dual-serving): `gcloud ... compute ssh family-app ... --command='cd /home/jc/family-task-manager && sudo docker compose --env-file .env -f docker-compose.gcp.yml stop tunnel'`.
- [ ] **Step 2:** Confirm `https://family.agent-ia.mx` still healthy (served only by .91).
- [ ] **Step 3:** Stop the GCP stack: `... down` (keep volumes). Pull one last full dump to local for cold archive if not already held.
- [ ] **Step 4:** Delete `gcp-family.agent-ia.mx` + `api-gcp-family.agent-ia.mx` public hostnames from the GCP tunnel (or delete the tunnel).
- [ ] **Step 5:** Delete the VM (after Juan confirms .91 stable ≥24h):
```bash
gcloud --account=info@agent-ia.mx --project=family-prod compute instances delete family-app --zone=us-central1-a
```

### Task 15: Update CLAUDE.md + memory

- [ ] **Step 1:** Rewrite the `CLAUDE.md` production section: canonical prod = 10.1.0.91 rootless podman, `docker-compose.onprem.yml`, `./scripts/deploy-onprem.sh`; on-prem ops incantations (rootless `podman compose`, never `sudo podman`); mark the GCP VM decommissioned (mirror the .99 note). Update the "Live at" URL to `https://family.agent-ia.mx`.
- [ ] **Step 2:** Change the top-level line 7 URL and line 38-42 tunnel block to the new host + hostnames.
- [ ] **Step 3:** Write a memory entry (`project` type): 10.1.0.91 is the new prod home; fresh CF tunnel token; rootless rules apply; `deploy-onprem.sh` is canonical. Add a pointer in `MEMORY.md`.
- [ ] **Step 4:** Commit docs, open the PR.

```bash
git add CLAUDE.md docs/
git commit -m "docs: canonical prod is on-prem 10.1.0.91; GCP decommissioned"
```

---

## Self-Review

**Spec coverage:** every spec section maps to a task — runtime model + rootless correctness (Tasks 3, 6, 9), new files (Tasks 3–6), compose deltas (Task 3), ingress/tunnel (Tasks 3, 7, 12), config/external touchpoints (Tasks 1, 2, 4, 13), cutover runbook (Tasks 10–12), decommission (Task 14), verification (Tasks 8, 12), docs/memory (Task 15). Added Tasks 1 & 2 (hardcoded-hostname parameterization) discovered during planning — real scope the spec implied under "grep for hardcoded old hostnames".

**Placeholder scan:** no TBD/TODO left as work items (the `backup-db.sh` GCS TODO is pre-existing, untouched). All code steps show concrete content.

**Type/name consistency:** container names (`family_onprem_*`), project name (`family-task-manager`), volume names (`family-task-manager_*`), hostnames (`family.agent-ia.mx`/`api-family.agent-ia.mx`), and `COMPOSE_CMD`/`COMPOSE_FILE`/`COMPOSE_PROJECT` env names are consistent across compose, deploy script, systemd units, and runbook.

## Risks / notes

- Phases 2–4 are live-ops; run them with Juan present. Phase 1 is safe repo work (can be autonomous/subagent).
- GCP box can't SSH directly to .91 → all data hops via the local mac (Tasks 10–11).
- Downtime window = Task 11 (stop GCP writes → restore verified on .91), ~10–20 min.
- Redis data intentionally not migrated (sessions ephemeral; users re-login).
- Keep the GCP final dump archived locally before Task 14 Step 5 (VM delete is irreversible).
