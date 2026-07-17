# Family Task Manager

Multi-tenant gamified family task manager. Each family is fully isolated. Includes points/rewards/consequences, native budget (17 models, 23 sub-routes), AI receipt scanner with HITL review queue, Jarvis AI copilot (MCP), and PayPal subscription billing.

Live: <https://family.agent-ia.mx>

## Stack

- Backend: Python 3.12, FastAPI, async SQLAlchemy 2.0, Alembic, PostgreSQL 15, Redis 7
- Frontend: Astro 5 + Tailwind CSS v4 (SSR via Node adapter)
- AI: Anthropic Claude via LiteLLM proxy (receipt/calendar scanning, Jarvis, translation)
- Subscriptions: PayPal (only)

## Local Development

```bash
cp .env.example .env                      # set SECRET_KEY (openssl rand -hex 32)
podman compose up -d                      # backend, frontend, postgres, test-db, redis

# Apps
# Frontend: http://localhost:3003
# Backend:  http://localhost:8003/docs
```

Run tests inside the backend container:

```bash
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/ -v
cd backend && ruff check app              # lint (CI-enforced)
```

E2E (Playwright):

```bash
cd e2e-tests && npm install
npm run test            # all
npm run test:budget     # budget only
```

## Production

- Host: on-prem `10.1.0.91` (RHEL 10, rootless podman, shared box — never `sudo podman`)
- App dir: `/home/jc/family-task-manager/`
- Compose: `docker-compose.onprem.yml`
- Public URLs: `https://family.agent-ia.mx` + `https://api-family.agent-ia.mx` via Cloudflare Tunnel `family-onprem`
- Secrets: `.env` on the host (template `.env.onprem.example`)

Deploy:

```bash
./scripts/deploy-onprem.sh        # canonical deploy (backup → rsync → build → migrate → up → smoke)
```

The GCP path (`scripts/deploy-gcp.sh`, `docker-compose.gcp.yml`) is retained for rollback only — decommissioned 2026-07-05.

## CI

`.github/workflows/ci.yml`: backend (ruff + alembic round-trip + full pytest w/ coverage gate) and frontend (astro check + build) on every push/PR to main.

## Service Ports

| Service       | External | Internal |
| ------------- | -------- | -------- |
| Frontend      | 3003     | 3000     |
| Backend API   | 8003     | 8000     |
| PostgreSQL    | 5437     | 5432     |
| Test DB       | 5435     | 5432     |
| Redis         | 6380     | 6379     |

## Documentation

- `CLAUDE.md` — canonical agent/dev context (architecture, conventions, ops)
- `ARCHITECTURE.md` — multi-tenant patterns
- `docs/DEPLOYMENT.md` — deployment procedures
- `docs/USER_GUIDE_EN.md` / `docs/USER_GUIDE_ES.md` — user guides (rendered at `/help` + `/ayuda`)
- `docs/OAUTH_PAYMENT_SETUP.md` — Google OAuth + PayPal setup
- `docs/JARVIS_MCP.md` — Jarvis MCP server

## Architecture Highlights

- Multi-tenant: every row scoped by `family_id`, enforced by JWT claim
- Clean architecture: Routes → Services → SQLAlchemy models
- Auth: JWT with `user_id` + `role` (PARENT/TEEN/CHILD) + `family_id`; sessions in Redis
- Native budget (Phase 10): no external Actual Budget dependency
- HITL review queue: low-confidence receipt scans (<30%) create `BudgetReceiptDraft` records for manual review
- Two-currency economy: chores/bonus tasks → points; gig board → cash ($MXN)

## Demo Login (after seeding)

```
mom@demo.com    / password123  (PARENT)
dad@demo.com    / password123  (PARENT)
emma@demo.com   / password123  (CHILD)
lucas@demo.com  / password123  (TEEN)
```

## Repository

- Origin: `https://github.com/staff-ai-0/family-task-manager.git`
- Stable: `main` (PR-based flow; CI must pass)
