# Family Task Manager

Multi-tenant gamified family task manager. Each family is fully isolated. Includes points/rewards/consequences, native budget (15 models, 18 sub-routes), AI receipt scanner with HITL review queue, subscription billing.

Live: <https://family.agent-ia.mx>

## Stack

- Backend: Python 3.12, FastAPI, async SQLAlchemy 2.0, Alembic, PostgreSQL 15, Redis 7
- Frontend: Astro 5 + Tailwind CSS v4 (SSR via Node adapter)
- AI: Anthropic Claude Vision (receipt scanner) + LiteLLM for translation
- Subscriptions: PayPal + Mercado Pago + Stripe

## Local Development

```bash
cp .env.example .env                      # set SECRET_KEY (openssl rand -hex 32)
docker compose up -d                       # backend, frontend, postgres, test-db, redis

# Apps
# Frontend: http://localhost:3003
# Backend:  http://localhost:8003/docs
```

Run tests inside the backend container:

```bash
docker exec -e PYTHONPATH=/app family_app_backend pytest tests/ -v
docker exec -e PYTHONPATH=/app family_app_backend pytest tests/ --cov=app --cov-report=html
```

E2E (Playwright):

```bash
cd e2e-tests && npm install
npm run test            # all
npm run test:budget     # budget only
```

## Production

- Host: `10.1.0.99` (RHEL 10, podman 5.6 rootless)
- App dir: `/mnt/nvme/docker-prod/family-task-manager/`
- Compose: `docker-compose.yml` (single file is prod-ready; `docker-compose.stage.yml` for staging)
- Public URL: `https://family.agent-ia.mx` via Cloudflare Tunnel
- Secrets: Vault path `secret/family-task-manager/prod` (periodic token in `.env` on host)

Deploy:

```bash
./deploy-prod.sh        # canonical on-prem deploy script
```

Per-repo gotcha (NVMe mode drift): `git config core.fileMode false`

## Service Ports

| Service       | External | Internal |
| ------------- | -------- | -------- |
| Frontend      | 3003     | 3000     |
| Backend API   | 8003     | 8000     |
| PostgreSQL    | 5437     | 5432     |
| Test DB       | 5435     | 5432     |
| Redis         | 6380     | 6379     |

## Documentation

- `CLAUDE.md` — agent context (full architecture, conventions)
- `AGENTS.md` — AI development guide
- `ARCHITECTURE.md` — multi-tenant patterns
- `docs/DEPLOYMENT.md` — deployment procedures
- `docs/USER_GUIDE_EN.md` / `docs/USER_GUIDE_ES.md` / `docs/MANUAL_USUARIO.md` — user guides
- `docs/OAUTH_PAYMENT_SETUP.md` — Google OAuth + payment provider setup
- `.github/instructions/` — coding standards (multi-tenant, type safety, testing)

## Architecture Highlights

- Multi-tenant: every row scoped by `family_id`, enforced by JWT claim
- Clean architecture: Routes → Services → SQLAlchemy models
- Auth: JWT with `user_id` + `role` (PARENT/TEEN/CHILD) + `family_id`; sessions in Redis
- Native budget (Phase 10): no external Actual Budget dependency. `/api/sync/*` returns 410 Gone permanently.
- HITL review queue: low-confidence receipt scans (<30%) create `BudgetReceiptDraft` records for manual review

## Demo Login (after seeding)

```
mom@demo.com    / password123  (PARENT)
dad@demo.com    / password123  (PARENT)
emma@demo.com   / password123  (CHILD)
lucas@demo.com  / password123  (TEEN)
```

## Repository

- Origin: `https://github.com/staff-ai-0/family-task-manager.git`
- Stable: `main`
- Active: `chore/budget-cleanup` (and topic branches)
