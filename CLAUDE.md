# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Family Task Manager** — gamified family chore/task app with points, rewards, and consequences. Multi-tenant by design (each family is fully isolated). Live at https://family.agent-ia.mx.

**Stack**: Python 3.12 + FastAPI (backend) · Astro 5 + Tailwind CSS v4 (frontend) · PostgreSQL 15 + Redis 7 · Docker Compose · Anthropic Claude API (receipt scanner)

> Note: `.github/copilot-instructions.md` is outdated (references Jinja2/HTMX/Flowbite/Render). The current frontend is Astro 5, not Jinja2 templates.

---

## Common Commands

### Docker (recommended workflow)

```bash
docker compose up -d                                          # Start all services
docker compose ps                                             # Status
docker compose logs -f backend                               # Logs

# Tests (run inside container)
docker exec -e PYTHONPATH=/app family_app_backend pytest tests/ -v
docker exec -e PYTHONPATH=/app family_app_backend pytest tests/test_auth.py -v
docker exec -e PYTHONPATH=/app family_app_backend pytest -k "test_name" -v
docker exec -e PYTHONPATH=/app family_app_backend pytest tests/ --cov=app --cov-report=html

# Migrations
docker exec family_app_backend alembic upgrade head
docker exec family_app_backend alembic revision --autogenerate -m "description"

# Seed demo data
docker exec family_app_backend python /app/seed_data.py
```

### Local development (without Docker)

```bash
# Backend
cd backend && source venv/bin/activate
export DATABASE_URL="postgresql+asyncpg://familyapp:familyapp123@localhost:5437/familyapp"
uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend && npm install && npm run dev      # localhost:3000
npm run build && npm run preview
```

### E2E Tests (Playwright)

```bash
cd e2e-tests && npm install
npm run test                  # All
npm run test:budget           # Budget suite only
npm run test:headed           # With visible browser
```

---

## Service Ports

| Service       | External | Internal |
|---------------|----------|----------|
| Frontend      | 3003     | 3000     |
| Backend API   | 8003     | 8000     |
| PostgreSQL    | 5437     | 5432     |
| Test DB       | 5435     | 5432     |
| Redis         | 6380     | 6379     |

- **API Docs**: http://localhost:8003/docs
- **Frontend**: http://localhost:3003
- **Frontend→Backend (SSR)**: uses internal Docker URL `http://backend:8000`

---

## Architecture

### Multi-tenant isolation (critical)

Every model with family data **must** have `family_id` as a non-nullable FK to `families.id`. Every service query **must** filter by `family_id` from the authenticated user's JWT. Never expose data across families.

### Clean architecture layers

```
Routes (HTTP only) → Services (business logic) → SQLAlchemy models (DB)
```

Routes must not contain business logic. Services own domain rules. Use `base_service.py` for common CRUD.

### Authentication

- JWT tokens contain `user_id`, `role`, `family_id`
- Sessions stored in Redis
- Roles: `PARENT` (full access), `TEEN` (extended), `CHILD` (limited)
- Auth cookies: `secure=True`, `httpOnly=True` in production

### API structure

All routes prefixed `/api/`. Key route groups:
- `/api/auth/` — register, login, OAuth callbacks
- `/api/tasks/` — legacy task model
- `/api/task-templates/` + `/api/task-assignments/` — current task system
- `/api/rewards/`, `/api/consequences/`, `/api/points-conversion/`
- `/api/subscriptions/` — plan management, PayPal integration
- `/api/budget/` — 17 sub-route groups (see Budget System below)
- `/api/sync/*` — **returns 410 Gone** (decommissioned; replaced by `/api/budget/`)

### Budget system

Fully native to PostgreSQL (the external "Actual Budget" service was decommissioned in Phase 10). Never re-introduce external budget dependencies.

**14 budget models** in `backend/app/models/budget.py`:
- Core: `BudgetCategoryGroup`, `BudgetCategory`, `BudgetAccount`, `BudgetPayee`, `BudgetTransaction`, `BudgetAllocation`
- Rules & Goals: `BudgetCategorizationRule`, `BudgetGoal`
- Scheduling: `BudgetRecurringTransaction`
- Organization: `BudgetSavedFilter`, `BudgetTag`, `BudgetTransactionTag`
- Analytics: `BudgetCustomReport`
- Sync (legacy): `BudgetSyncState`

**17 budget sub-routes** (`/api/budget/`):
- Core CRUD: `categories`, `accounts`, `transactions`, `allocations`, `payees`, `transfers`
- Time: `month` (single month view), `months` (month locking)
- Rules: `categorization-rules`
- Goals: `goals`
- Scheduling: `recurring-transactions`
- Data: `recycle-bin`, `saved-filters`, `tags`
- Import/Export: `transactions/import/csv`, `transactions/import/file` (OFX/QIF/CAMT), `transactions/scan-receipt` (AI), `export`, `import-backup`
- Analytics: `reports`, `custom-reports`
- Templates: `allocations/auto-fill` (5 strategies)

**19 budget services** in `backend/app/services/budget/`:
`account`, `allocation`, `categorization_rule`, `category`, `csv_import`, `custom_report`, `export`, `file_import`, `goal`, `month_locking`, `payee`, `receipt_scanner`, `recurring_transaction`, `recycle_bin`, `report`, `saved_filter`, `tag`, `transaction`, `transfer`

### Subscription & premium gating

3-tier plan system (Free / Plus / Pro) with PayPal billing integration.

- Models: `SubscriptionPlan`, `FamilySubscription`, `UsageTracking` in `backend/app/models/subscription.py`
- Feature gating: `backend/app/core/premium.py` — `require_feature()` checks plan limits
- Metered features: `receipt_scan`, `budget_transaction`, `recurring_transaction`, `family_member`, `budget_account`
- Boolean features: `budget_reports`, `budget_goals`, `csv_import`, `ai_features`

### AI Receipt Scanner

Uses Anthropic Claude Vision API to extract transaction data from receipt photos.

- Service: `backend/app/services/budget/receipt_scanner_service.py`
- Endpoint: `POST /api/budget/transactions/scan-receipt` (parent only, premium gated)
- Frontend: `/budget/scan-receipt` (camera capture + file upload + drag-drop)
- Requires `ANTHROPIC_API_KEY` env var

### Frontend (Astro 5)

Pages live in `frontend/src/pages/`. Routing is file-based. All server-side API calls go to `http://backend:8000` (internal Docker network). Auth state managed via cookies + Astro middleware (`frontend/src/middleware.ts`).

Key frontend pages:
- `/budget/` — main budget dashboard
- `/budget/transactions` — transaction list with filters
- `/budget/scan-receipt` — AI receipt scanner
- `/budget/import` — CSV import
- `/budget/reports/` — spending reports
- `/parent/settings/subscription` — plan management

---

## Key files

| File | Purpose |
|------|---------|
| `backend/app/main.py` | FastAPI app setup, middleware, router registration |
| `backend/app/core/config.py` | All env vars via Pydantic settings |
| `backend/app/core/dependencies.py` | `get_current_user` and other FastAPI deps |
| `backend/app/core/premium.py` | Feature gating, plan resolution, usage limits |
| `backend/app/services/base_service.py` | CRUD base class — extend for new services |
| `backend/app/models/budget.py` | All 14 budget tables |
| `backend/app/models/subscription.py` | Subscription plans, family subscriptions, usage tracking |
| `backend/app/services/budget/receipt_scanner_service.py` | Claude Vision receipt scanning |
| `backend/app/services/budget/file_import_service.py` | OFX/QIF/CAMT parsers |
| `backend/app/services/budget/export_service.py` | Budget export/import as ZIP |
| `backend/tests/conftest.py` | Test fixtures, test DB setup |
| `frontend/src/middleware.ts` | Auth/session middleware for Astro SSR |
| `docker-compose.yml` | All 5 services orchestrated here |

---

## Environment variables

Key env vars (set in `.env` or `docker-compose.yml`):

| Variable | Purpose | Required |
|----------|---------|----------|
| `DATABASE_URL` | PostgreSQL connection | Yes |
| `SECRET_KEY` | JWT signing key | Yes |
| `REDIS_URL` | Redis connection | Yes |
| `ANTHROPIC_API_KEY` | Claude Vision for receipt scanning | For AI features |
| `GOOGLE_CLIENT_ID/SECRET` | Google OAuth | For Google login |
| `PAYPAL_CLIENT_ID/SECRET` | PayPal subscriptions | For billing |
| `RESEND_API_KEY` | Transactional emails | For email features |
| `LITELLM_API_BASE/KEY` | Auto-translation | For translation |

---

## Testing

- **477 tests collected**, 416 passing (51 failures are pre-existing stubs for unimplemented advanced features)
- Use the separate **test database** (port 5435) — `conftest.py` creates/drops schema per run
- All new features need tests before merging
- Test files follow pattern: `tests/test_<feature>.py`

Key test files:
- `test_wave1_gap_closure.py` — 22 tests (payee favorites/merge, schedule end modes)
- `test_wave2_gap_closure.py` — 28 tests (saved filters, rule actions, tags)
- `test_wave3_gap_closure.py` — 30 tests (file import, auto-fill, export, custom reports)
- `test_receipt_scanner.py` — 6 tests (Claude Vision mocked, scan+create flow)
- `test_subscription.py` — subscription/premium gating tests

## Database migrations

Always use Alembic — never modify the DB schema with raw SQL. Test migrations locally before production.

Current migration chain (latest):
```
... → subscription_tables → wave1_budget_gap_closure → wave2_saved_filters_tags → wave3_custom_reports_table
```

## Demo credentials (after seeding)

```
mom@demo.com / password123    (PARENT)
dad@demo.com / password123    (PARENT)
emma@demo.com / password123   (CHILD)
lucas@demo.com / password123  (TEEN)
```
