# Family Task Manager — Architecture

## Overview

Multi-tenant SaaS. Each family is an isolated tenant; every row carries `family_id`. Three layers: Astro 5 SSR frontend ↔ FastAPI JSON backend ↔ PostgreSQL + Redis. AI features (receipt/calendar scanning, Jarvis copilot, translation) call out via the AgentIA LiteLLM proxy to Anthropic Claude.

## Component Diagram

```
                       Cloudflare Tunnel (family-onprem)
                              │
                              ▼
        ┌─────────────────────────────────────────────┐
        │     family_onprem_frontend (Astro 5)        │   ← :3003 (local) / :3000 (container)
        │     SSR, Tailwind CSS v4, JWT in cookie     │
        └────────────────────┬────────────────────────┘
                             │  internal: http://backend:8000
                             ▼
        ┌─────────────────────────────────────────────┐
        │     family_onprem_backend (FastAPI)         │   ← :8003 (local) / :8000 (container)
        │  async SQLAlchemy 2.0, Pydantic v2          │
        │  routes → services → models                 │
        └─────────┬─────────────┬─────────────────────┘
                  │             │
                  ▼             ▼
       PostgreSQL 15      Redis 7 (sessions)
       (familyapp :5437)  :6380
                  ▲
                  │ test isolation
       Test DB (postgres :5435)

                  ┌────────────────────────────┐
                  │  External AI services      │
                  │  LiteLLM proxy             │
                  │  (litellm.agent-ia.mx)     │
                  │  → Anthropic Claude        │
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
Task templates + weekly assignments (shuffle engine with rotation/carry). Points awarded on completion, redeemable in family-defined reward catalog. Missed mandatory tasks trigger configurable consequences.

### Two-Currency Economy
Chores + bonus tasks earn **points** (privileges). The gig board (`/api/gigs`) pays **cash** ($MXN, `cash_cents` + `cash_transactions`). Family Bank (`/api/bank`) adds match/interest/allowance payday sweeps.

### Native Budget System (Phase 10)
Fully native to PostgreSQL. The external "Actual Budget" sync service was decommissioned in Phase 10 (its `/api/sync/*` 410 stubs were removed 2026-07-16).

17 budget models in `backend/app/models/budget.py`, 23 sub-routes under `/api/budget/`, 28 services in `backend/app/services/budget/`. Includes envelope categories, accounts, payees, scheduled transactions, categorization rules, goals, recycle bin, custom reports, and CSV/OFX/QIF/CAMT import.

### AI Receipt Scanner + HITL Queue
Receipt photos/PDFs → PyMuPDF rasterization (PDFs) → Claude Vision (via LiteLLM, model alias `claude-haiku`) → structured transaction extraction. Low-confidence scans (<30% or no detectable total) create a `BudgetReceiptDraft` record routed to `/budget/receipt-drafts` for parent review instead of being discarded.

### Jarvis (AI copilot + MCP)
Parent-facing LLM assistant (tool-calling + SSE streaming) with cron-driven scheduled prompts and an in-repo MCP server (`/mcp`, off by default). Destructive operations are HITL-gated. See `docs/JARVIS_MCP.md`.

### Subscriptions
3-tier (Free / Plus / Pro). Billing via **PayPal only**. Feature gating in `backend/app/core/premium.py` (`require_feature()`) checks plan limits — both metered (`receipt_scan`, `budget_transaction`, etc.) and boolean (`csv_import`, `ai_features`, etc.) features. Every LLM call site is gated behind `ai_features`.

## Authentication

- JWT tokens carry `user_id`, `role` (`PARENT` / `TEEN` / `CHILD`), `family_id`; access+refresh cookie pair with transparent refresh in the Astro middleware
- Sessions tracked in Redis
- Auth cookies: `secure=True`, `httpOnly=True`, `SameSite=Lax` in production
- CSRF origin check + CSP/security headers in `frontend/src/middleware.ts`
- Google OAuth for sign-in (web + native client IDs), PayPal for billing

## Data Persistence

- **PostgreSQL 15** — primary store; async via asyncpg
- **Redis 7** — sessions and ephemeral state
- **Test DB** (separate PG instance, port 5435) — schema created/dropped per test session via `conftest.py`
- **Alembic** — sole source of schema changes (no raw SQL migrations); single-head chain

## Deployment

- Local dev: `podman compose up -d` (one compose file covers all services)
- Production: `./scripts/deploy-onprem.sh` → on-prem `10.1.0.91:/home/jc/family-task-manager/` (rootless podman, compose file `docker-compose.onprem.yml`)
- Public ingress: Cloudflare Tunnel only (no direct IP exposure); tunnel routes target container names
- Secrets: `.env` on the prod host (no Vault dependency in the live path)
- GCP path retained for rollback only (decommissioned 2026-07-05)

## Testing

- pytest suite in `backend/tests/` (~1760 tests; CI gates on it plus `ruff check`)
- Playwright E2E in `e2e-tests/` (budget, auth, gigs, chat, kiosk, Jarvis, …)
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
| Compose (dev / prod) | `docker-compose.yml` / `docker-compose.onprem.yml` |
| Deploy script | `scripts/deploy-onprem.sh` |
| CI | `.github/workflows/ci.yml` |
