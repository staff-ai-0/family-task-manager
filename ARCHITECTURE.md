# Family Task Manager — Architecture

## Overview

Multi-tenant SaaS. Each family is an isolated tenant; every row carries `family_id`. Three layers: Astro 5 SSR frontend ↔ FastAPI JSON backend ↔ PostgreSQL + Redis. AI features (receipt scanner, translation) call out via Anthropic Claude and the AgentIA LiteLLM proxy.

## Component Diagram

```
                       Cloudflare Tunnel
                              │
                              ▼
        ┌─────────────────────────────────────────────┐
        │          ftm_frontend (Astro 5)             │   ← :3003 (host) / :3000 (container)
        │     SSR, Tailwind CSS v4, JWT in cookie     │
        └────────────────────┬────────────────────────┘
                             │  internal: http://backend:8000
                             ▼
        ┌─────────────────────────────────────────────┐
        │         ftm_backend (FastAPI)               │   ← :8003 (host) / :8000 (container)
        │  async SQLAlchemy 2.0, Pydantic v2          │
        │  routes → services → models                 │
        └─────────┬─────────────┬─────────────┬───────┘
                  │             │             │
                  ▼             ▼             ▼
       PostgreSQL 15      Redis 7      Vault (platform)
       (familyapp)     (sessions)    secret/family-task-manager/prod
       :5437               :6380          :8200
                  ▲
                  │ test isolation
       Test DB (postgres :5435)

                  ┌────────────────────────────┐
                  │  External AI services      │
                  │  Anthropic Claude (vision) │
                  │  LiteLLM proxy (10.1.0.99) │
                  └────────────────────────────┘
```

## Multi-Tenancy

- Every model with family-scoped data has `family_id: UUID` non-null FK to `families.id`.
- Every service query filters on `family_id` from the authenticated user's JWT claim.
- No cross-family reads are permitted; integration tests assert isolation.

## Clean Architecture

```
HTTP Routes  → Service Layer (business logic, validation) → SQLAlchemy Models
(no logic)     (`backend/app/services/`)                    (`backend/app/models/`)
```

`base_service.py` provides common CRUD; specialized services compose it.

## Domain Surface

### Tasks / Rewards / Consequences
Default tasks (must complete) vs extra tasks (optional, unlock when defaults done). Points awarded on completion, redeemable in family-defined reward catalog. Missed default tasks trigger configurable consequences (screen-time limits, reward suspension).

### Native Budget System (Phase 10)
Fully native to PostgreSQL. The external "Actual Budget" sync service was decommissioned in Phase 10 — `/api/sync/*` returns `410 Gone` permanently.

15 budget models in `backend/app/models/budget.py`, 18 sub-routes under `/api/budget/`, 20 services in `backend/app/services/budget/`. Includes envelope categories, accounts, payees, scheduled transactions, categorization rules, goals, recycle bin, custom reports, and CSV/OFX/QIF/CAMT import.

### AI Receipt Scanner + HITL Queue
Receipt photos/PDFs → PyMuPDF rasterization (PDFs) → Claude Vision (via LiteLLM, model alias `claude-haiku`) → structured transaction extraction. Low-confidence scans (<30% or no detectable total) create a `BudgetReceiptDraft` record routed to `/budget/receipt-drafts` for parent review instead of being discarded.

### Subscriptions
3-tier (Free / Plus / Pro). Billing via PayPal, Mercado Pago, Stripe. Feature gating in `backend/app/core/premium.py` (`require_feature()`) checks plan limits — both metered (`receipt_scan`, `budget_transaction`, etc.) and boolean (`csv_import`, `ai_features`, etc.) features.

## Authentication

- JWT tokens carry `user_id`, `role` (`PARENT` / `TEEN` / `CHILD`), `family_id`
- Sessions tracked in Redis
- Auth cookies: `secure=True`, `httpOnly=True`, `SameSite=Lax` in production
- CSRF middleware bound to the public origin (`family.agent-ia.mx`)
- Google OAuth for sign-in, PayPal/MP/Stripe OAuth for billing

## Data Persistence

- **PostgreSQL 15** — primary store; async via asyncpg
- **Redis 7** — sessions and ephemeral state
- **Test DB** (separate PG instance, port 5435) — schema created/dropped per test session via `conftest.py`
- **Alembic** — sole source of schema changes (no raw SQL migrations)

## Deployment

- Local dev: `docker compose up -d` (one compose file covers all services)
- Production: `./deploy-prod.sh` deploys to `10.1.0.99:/mnt/nvme/docker-prod/family-task-manager/` via podman-compatible shim
- Compose: `docker-compose.yml` (single file is prod-ready); `docker-compose.stage.yml` for staging
- Public ingress: Cloudflare Tunnel only (no direct IP exposure)
- Vault: periodic per-app token in `.env` on prod host; secrets at `secret/family-task-manager/prod`

NVMe host gotcha: `git config core.fileMode false` per repo (drive mangles 644→755 on checkout).

## Testing

- pytest suite in `backend/tests/` (~470+ collected)
- Playwright E2E in `e2e-tests/` (~71 tests covering budget, auth, receipt scanner, HITL queue)
- All new features ship with tests; multi-tenant isolation tests must pass

## Where Things Live

| Concern | Location |
| ------- | -------- |
| FastAPI app entrypoint | `backend/app/main.py` |
| Pydantic settings | `backend/app/core/config.py` |
| Auth dependencies | `backend/app/core/dependencies.py` |
| Premium / feature gating | `backend/app/core/premium.py` |
| Service base class | `backend/app/services/base_service.py` |
| Budget models | `backend/app/models/budget.py` |
| Subscription models | `backend/app/models/subscription.py` |
| Receipt scanner service | `backend/app/services/budget/receipt_scanner_service.py` |
| Astro middleware | `frontend/src/middleware.ts` |
| Compose | `docker-compose.yml` |
| Deploy script | `deploy-prod.sh` |
