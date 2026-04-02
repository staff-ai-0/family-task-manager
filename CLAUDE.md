# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Family Task Manager** — gamified family chore/task app with points, rewards, and consequences. Multi-tenant by design (each family is fully isolated). Live at https://family.agent-ia.mx.

**Stack**: Python 3.12 + FastAPI (backend) · Astro 5 + Tailwind CSS v4 (frontend) · PostgreSQL 15 + Redis 7 · Docker Compose

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
| Backend API   | 8002     | 8000     |
| PostgreSQL    | 5437     | 5432     |
| Test DB       | 5435     | 5432     |
| Redis         | 6380     | 6379     |

- **API Docs**: http://localhost:8002/docs
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
- `/api/budget/` — 17 sub-routes (categories, accounts, transactions, allocations, reports, goals, recycle_bin, recurring, rules, transfers, months, CSV import)
- `/api/sync/*` — **returns 410 Gone** (decommissioned; replaced by `/api/budget/`)

### Budget system (Phase 10)

Fully native to PostgreSQL. The external "Actual Budget" service was decommissioned. Budget models live in `backend/app/models/budget.py` (7 tables). Never re-introduce external budget dependencies.

### Frontend (Astro 5)

Pages live in `frontend/src/pages/`. Routing is file-based. All server-side API calls go to `http://backend:8000` (internal Docker network). Auth state managed via cookies + Astro middleware (`frontend/src/middleware.ts`).

---

## Key files

| File | Purpose |
|------|---------|
| `backend/app/main.py` | FastAPI app setup, middleware, router registration |
| `backend/app/core/config.py` | All env vars via Pydantic settings |
| `backend/app/core/dependencies.py` | `get_current_user` and other FastAPI deps |
| `backend/app/services/base_service.py` | CRUD base class — extend for new services |
| `backend/app/models/budget.py` | All 7 budget tables in one file |
| `backend/tests/conftest.py` | Test fixtures, test DB setup |
| `frontend/src/middleware.ts` | Auth/session middleware for Astro SSR |
| `docker-compose.yml` | All 5 services orchestrated here |

---

## Testing requirements

- Maintain **70%+ coverage** (currently ~74%, 118+ tests)
- Use the separate **test database** (port 5435) — `conftest.py` creates/drops schema per run
- All new features need tests before merging

## Database migrations

Always use Alembic — never modify the DB schema with raw SQL. Test migrations locally before production.

## Demo credentials (after seeding)

```
mom@demo.com / password123    (PARENT)
dad@demo.com / password123    (PARENT)
emma@demo.com / password123   (CHILD)
lucas@demo.com / password123  (TEEN)
```
