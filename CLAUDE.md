# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Family Task Manager** — gamified family chore/task app with points, rewards, and consequences. Multi-tenant by design (each family is fully isolated). Live at https://family.agent-ia.mx.

**Stack**: Python 3.12 + FastAPI (backend) · Astro 5 + Tailwind CSS v4 (frontend) · PostgreSQL 15 + Redis 7 · rootless Podman (prod) · Anthropic Claude via LiteLLM proxy (AI features)

**Environments**:
- Local (dev): frontend `http://localhost:3003`, backend `http://localhost:8003/docs` — secrets in `.env`
- **Production (on-prem 10.1.0.91) — CANONICAL (since 2026-07-05)**: `https://family.agent-ia.mx` + `https://api-family.agent-ia.mx` (Cloudflare Tunnel `family-onprem`). RHEL 10 rootless podman under user `jc`. App at `/home/jc/family-task-manager/`, compose file `docker-compose.onprem.yml`, secrets in `.env` on host (template `.env.onprem.example`). Deploy via `./scripts/deploy-onprem.sh` (config in `.deploy.onprem.env`). SHARED box (school-admin/medical/platform/vault also run here) — never `sudo podman` (global `~/.claude/CLAUDE.md` rootless rules apply).
- **GCP (`family-app`) — DECOMMISSIONED 2026-07-05**: VM stopped (not deleted), volumes kept for rollback. Final pre-cutover dump at `backups/prod-cutover-gcp-20260705.sql` (local + on .91). `scripts/deploy-gcp.sh` / `docker-compose.gcp.yml` / `.deploy.gcp.env` / `scripts/gcp-bootstrap.sh` retained for rollback ONLY — do NOT deploy there without reassessment.
- **On-prem (10.1.0.99) — DECOMMISSIONED 2026-05-23**: predecessor host; systemd unit disabled, DB dump retained on that host. Do NOT redeploy there. (The box itself still hosts the shared LiteLLM proxy at `litellm.agent-ia.mx`.)

**Production deployment**: `./scripts/deploy-onprem.sh` is the canonical path (target: 10.1.0.91) — rsyncs source over SSH, builds images with rootless `podman compose`, pins network DNS + chowns volumes, runs alembic migrations against the new image, brings the stack up (scoped `down` + `up` so stale images never survive), smoke-checks the public endpoints. Local `docker-compose.yml` is for dev only.

**Cloudflare Tunnel `family-onprem`** routes the public hostnames (per-stack `cloudflared` container on .91, configured in the Zero Trust dashboard):
- `family.agent-ia.mx` → `http://family_onprem_frontend:3000`
- `api-family.agent-ia.mx` → `http://family_onprem_backend:8000`

Routes MUST target the **container names**, not bare `frontend`/`backend`: on rootless netavark the tunnel joins the egress `frontend` net ONLY (`backend` is dual-homed there as `family_onprem_backend`). That egress net pins explicit DNS (`--dns 1.1.1.1 8.8.8.8`, done by `deploy-onprem.sh`) because the host resolv.conf's IPv6 link-local upstream breaks aardvark external forwarding — without it the connector can't reach Cloudflare's edge (HTTP 530) and backend egress (LiteLLM/OAuth/PayPal/SMTP) fails to resolve. Google OAuth redirect URI is `https://family.agent-ia.mx/auth/google/callback`.

## CI

`.github/workflows/ci.yml` runs on every push/PR to main:
- **backend** — `ruff check app` (zero-tolerance, config in `backend/ruff.toml`), alembic upgrade/downgrade round-trip, full pytest suite against postgres:15 + redis:7 services (coverage gate ≥70% from `pytest.ini`)
- **frontend** — `npm ci` + `astro check` + `astro build`

---

## Common Commands

### Production ops (on-prem .91, rootless podman as jc)

```bash
./scripts/deploy-onprem.sh            # full deploy (backup → rsync → build → migrate → up → smoke)
./scripts/deploy-onprem.sh --dry-run  # print remote commands only
ssh jc@10.1.0.91 'podman ps'          # status (NEVER sudo podman)
ssh jc@10.1.0.91 'podman logs -f family_onprem_backend'
./scripts/backup-db.sh                # on-demand DB dump
./scripts/restore-db.sh               # restore helper
```

### Local dev (podman compose)

```bash
podman compose up -d                                          # Start all services
podman compose ps                                             # Status
podman compose logs -f backend                                # Logs

# Tests (run inside container)
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/ -v
podman exec -e PYTHONPATH=/app family_app_backend pytest -k "test_name" -v
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/ --cov=app --cov-report=html

# Lint
cd backend && ruff check app

# Migrations
podman exec family_app_backend alembic upgrade head
podman exec family_app_backend alembic revision --autogenerate -m "description"

# Seed demo data
podman exec family_app_backend python /app/seed_data.py
```

When podman is down locally, the suite also runs bare-metal (Homebrew PG on 5435 + local redis + `backend/.venv/bin/pytest --no-cov`).

### Local development (without containers)

```bash
# Backend
cd backend && source venv/bin/activate
export DATABASE_URL="postgresql+asyncpg://familyapp:familyapp123@localhost:5437/familyapp"
uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend && npm install && npm run dev      # localhost:3000
npm run check && npm run build
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
- **Frontend→Backend (SSR)**: uses internal container URL `http://backend:8000`

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

- JWT tokens contain `user_id`, `role`, `family_id`; access+refresh pair in httpOnly cookies
- Sessions stored in Redis
- Roles: `PARENT` (full access), `TEEN` (extended), `CHILD` (limited)
- Prefer the `require_parent_role` dependency (`app/core/dependencies.py`) over inline role checks
- Google OAuth accepts multiple client IDs: `GOOGLE_CLIENT_ID` (web) plus `GOOGLE_CLIENT_IDS` (comma list, for native iOS/Android client IDs under the same Cloud project). `GoogleOAuthService.verify_google_token` skips library-level `aud` validation and checks against the union manually (`backend/app/services/google_oauth_service.py`).

### JSON serialization for strict clients (iOS Swift, Android Kotlin)

SQLAlchemy `func.sum` over a `BigInteger` column returns a `Decimal` under asyncpg. Pydantic v2 serializes `Decimal` as a JSON **string** even when the schema field is typed `int` — strict-decoding mobile clients then fail with `Expected Int but found String`. **Always cast aggregated numeric values to `int()` before assigning to a Pydantic field.** Canonical pattern: `backend/app/api/routes/budget/accounts.py` (the `list_accounts` enrichment loop).

### API structure

All routes prefixed `/api/`. Key route groups:
- `/api/auth/` — register, login, OAuth callbacks
- `/api/task-templates/` + `/api/task-assignments/` — the task system (the pre-2026 legacy `/api/tasks` system was fully removed 2026-07-16: code, model, and — via the `drop_legacy_tasks` migration — its table)
- `/api/rewards/`, `/api/consequences/`, `/api/points-conversion/`
- `/api/subscriptions/` — plan management, PayPal integration
- `/api/budget/` — 23 sub-route groups (see Budget System below)
- Full domain list: see "Additional domains" table below

### Budget system

Fully native to PostgreSQL (the external "Actual Budget" service was decommissioned in Phase 10; the old `/api/sync/*` 410 stubs were removed 2026-07-16). Never re-introduce external budget dependencies.

**Account list endpoint includes computed balance**: `GET /api/budget/accounts/` enriches every row with `balance_cents` + `cleared_balance_cents` (both `Optional[int]`, populated only by list endpoints — null on POST/PUT responses). Avoids N+1 calls from clients. `starting_balance` is the seed value at account creation; when non-zero `AccountService.create` auto-inserts a synthetic "Starting Balance" transaction so the computed balance is correct from day one.

**17 budget models** in `backend/app/models/budget.py`:
- Core: `BudgetCategoryGroup`, `BudgetCategory`, `BudgetAccount`, `BudgetPayee`, `BudgetTransaction`, `BudgetAllocation` (+ transaction items/splits)
- Rules & Goals: `BudgetCategorizationRule`, `BudgetGoal`
- Scheduling: `BudgetRecurringTransaction`
- Organization: `BudgetSavedFilter`, `BudgetTag`, `BudgetTransactionTag`
- Analytics: `BudgetCustomReport`
- HITL: `BudgetReceiptDraft` — low-confidence scans pending human review
- Sync (legacy table): `BudgetSyncState`

**23 budget sub-routes** (`backend/app/api/routes/budget/`):
- Core CRUD: `categories`, `accounts`, `transactions`, `allocations`, `payees`, `transfers`
- Time: `month` (single month view), `months` (month locking)
- Rules: `categorization-rules` · Goals: `goals` · Scheduling: `recurring-transactions`
- Data: `recycle-bin`, `saved-filters`, `tags`
- HITL: `receipt-drafts` (list pending / approve / reject low-confidence scans)
- Import/Export: `transactions/import/csv`, `transactions/import/file` (OFX/QIF/CAMT), `transactions/scan-receipt` (AI), `export`, `import-backup`
- Analytics: `reports`, `custom-reports` · Templates: `allocations/auto-fill` (5 strategies)

**28 budget services** in `backend/app/services/budget/` — one per concern; notable beyond the CRUD set: `a2a_webhook_service` (bank-email-matcher agent intake), `account_matching_service`, `category_ai_service`, `dedup_service`, `duplicate_guard_service`, `transfer_detector`, `transaction_item_service`, `default_categories`.

### Subscription & premium gating

3-tier plan system (Free / Plus / Pro) with PayPal billing integration (PayPal ONLY — no Stripe, no Mercado Pago).

- Models: `SubscriptionPlan`, `FamilySubscription`, `UsageTracking` in `backend/app/models/subscription.py`
- Feature gating: `backend/app/core/premium.py` — `require_feature()` checks plan limits
- Metered features: `receipt_scan`, `budget_transaction`, `recurring_transaction`, `family_member`, `budget_account`
- Boolean features: `budget_reports`, `budget_goals`, `csv_import`, `ai_features`
- **Every LLM call site must be gated** (`require_feature("ai_features")` or `family_tier_allows`); regression suite `test_ai_gating.py`

### AI Receipt Scanner

Uses Claude Vision via LiteLLM proxy to extract transaction data from receipt photos/PDFs.

- Service: `backend/app/services/budget/receipt_scanner_service.py` (also exports the shared `LLM_TIMEOUT` used by every LLM call site)
- Endpoint: `POST /api/budget/transactions/scan-receipt` (parent only, premium gated)
- Frontend: `/budget/scan-receipt` (camera capture + file upload + drag-drop; accepts JPEG/PNG/WebP/PDF)
- Routes through LiteLLM proxy (`LITELLM_API_BASE` / `LITELLM_API_KEY`) using model alias `claude-haiku`
- PDFs are rasterized to JPEG (first page only, capped at 3000px, quality 85) via PyMuPDF before sending to vision API

### HITL Receipt Review Queue

Low-confidence scans (<30% or no detectable total) create a `BudgetReceiptDraft` record instead of being discarded.

- Model: `BudgetReceiptDraft` · Service: `receipt_draft_service.py`
- Endpoints: `GET/POST/DELETE /api/budget/receipt-drafts/` (parent only)
- Frontend: `/budget/receipt-drafts` — review queue with pre-filled editable form per draft
- Nav badge: red dot on clipboard icon in `BudgetNavNew` shows pending count on all budget pages

### Additional domains (beyond budget/task/gig)

Fully wired (routes + services + models + frontend), multi-tenant by `family_id`:

| Domain | Routes | Notes |
|--------|--------|-------|
| **Jarvis** (AI copilot) | `/api/jarvis`, `/api/jarvis/schedules`, `/mcp` | Parent-facing LLM assistant via LiteLLM (tool-calling + SSE streaming) + cron-driven scheduled prompts. MCP server (`/mcp`) + in-app MCP client; full family-scoped CRUD over activity domains; destructive ops HITL-gated. See `docs/JARVIS_MCP.md`. |
| **Pet** | `/api/pet` | Gamified virtual pet per kid (`kid_pet`, `pup_snapshot`); decays over time, fed by completing work. |
| **Meals** | `/api/meals` | Meal planning + recipe import; syncs to shopping lists. |
| **Shopping** | `/api/shopping` | Family shopping lists; receipt-scan + meal-plan integration. |
| **Calendar** | `/api/calendar` | Family events + AI calendar-image scanner. |
| **Chat / DM** | `/api/chat`, `/api/dm` | Family group chat (reactions, read state) + direct messages. |
| **Kiosk** | `/api/kiosk` | Shared-device kiosk mode (`kiosk_device`). |
| **Analytics** | `/api/analytics` | Family "PUP" snapshots / progress analytics. |
| **Gigs / Cash / Bank** | `/api/gigs`, `/api/cash`, `/api/bank` | Two-currency economy: chores+bonus → points; gig BOARD → cash ($MXN). Family Bank (match/interest/allowance payday sweep). |
| **Consequences / Rewards / Points** | `/api/consequences`, `/api/rewards`, `/api/points-conversion` | Discipline + reward economy on top of the points system. |

Production-readiness audits live in `docs/audit/` (2026-06-04 techdebt, 2026-07-02 UX, 2026-07-07 launch gaps).

### Frontend (Astro 5)

Pages live in `frontend/src/pages/` (file-based routing, SSR via Node adapter, no client framework — vanilla `<script>` islands). All server-side API calls go through same-origin Astro proxy routes (`/api/*`) to `http://backend:8000`. Auth state via cookies + `frontend/src/middleware.ts` (CSP/security headers, CSRF origin check, transparent token refresh).

Key frontend pages:
- `/budget/` — dashboard · `/budget/transactions` · `/budget/scan-receipt` · `/budget/receipt-drafts` · `/budget/import` · `/budget/reports/`
- `/gigs`, `/bank`, `/pet`, `/calendar`, `/chat`, `/kiosk`
- `/parent/settings/subscription` — plan management
- `/help` + `/ayuda` — user guides rendered from `docs/USER_GUIDE_{EN,ES}.md` (the `frontend/docs` symlink + root build context exist for this)

---

## Key files

| File | Purpose |
|------|---------|
| `backend/app/main.py` | FastAPI app setup, middleware, router registration, scheduler sweeps |
| `backend/app/core/config.py` | All env vars via Pydantic settings |
| `backend/app/core/dependencies.py` | `get_current_user`, `require_parent_role` |
| `backend/app/core/premium.py` | Feature gating, plan resolution, usage limits |
| `backend/app/services/base_service.py` | CRUD base class — extend for new services |
| `backend/app/models/budget.py` | All 17 budget tables |
| `backend/app/models/subscription.py` | Subscription plans, family subscriptions, usage tracking |
| `backend/ruff.toml` | Lint config (CI-enforced) |
| `backend/tests/conftest.py` | Test fixtures, test DB setup |
| `frontend/src/middleware.ts` | Auth/session/security-header middleware for Astro SSR |
| `.github/workflows/ci.yml` | CI (ruff + migrations round-trip + pytest; astro check + build) |
| `docker-compose.yml` | Local dev compose (all services) |
| `docker-compose.onprem.yml` | Production compose (used by `./scripts/deploy-onprem.sh`) |
| `scripts/deploy-onprem.sh` | Canonical production deploy script (target: 10.1.0.91) |
| `docker-compose.gcp.yml` + `scripts/deploy-gcp.sh` | **ROLLBACK ONLY** — decommissioned GCP path |

---

## Environment variables

Key env vars (set in `.env` — local, and on the prod host; templates `.env.example` / `.env.onprem.example`):

| Variable | Purpose | Required |
|----------|---------|----------|
| `DATABASE_URL` | PostgreSQL connection | Yes |
| `SECRET_KEY` | JWT signing key | Yes |
| `REDIS_URL` | Redis connection | Yes |
| `LITELLM_API_BASE/KEY` | All AI features (receipt/calendar scan, Jarvis, translation) | For AI features |
| `GOOGLE_CLIENT_ID/SECRET` | Google OAuth | For Google login |
| `PAYPAL_CLIENT_ID/SECRET` | PayPal subscriptions | For billing |
| `RESEND_API_KEY` / SMTP vars | Transactional emails | For email features |

`app/core/vault_bootstrap.py` still folds Vault KV into env WHEN `VAULT_ADDR`/`VAULT_TOKEN` are set — current prod does not set them (secrets live in `.env` on the host).

---

## Testing

- **~1760 tests**, full suite green; CI blocks on it (plus coverage gate ≥70%)
- Use the separate **test database** (port 5435) — `conftest.py` creates/drops schema per run
- All new features need tests before merging
- Test files follow pattern: `tests/test_<feature>.py`

## Database migrations

Always use Alembic — never modify the DB schema with raw SQL. Test migrations locally before production. Single-head chain (102 revisions as of 2026-07-16); CI exercises upgrade → downgrade -1 → upgrade.

## Demo credentials (after seeding)

```
mom@demo.com / password123    (PARENT)
dad@demo.com / password123    (PARENT)
emma@demo.com / password123   (CHILD)
lucas@demo.com / password123  (TEEN)
```

## Reference data (prod)

- Real user: `juan.mtz79@gmail.com` (PARENT, family_id `1998e48d-2ef0-48b6-a437-cbb730ae935c`); second parent `mayra.escamilla79@gmail.com`. Family name "Juan Carlos Martinez's Family".
- Tasks / gigs / budget data was fully reset on 2026-06-23 (per user request); the family starts clean. Pre-reset dump retained (see backups on the prod host).
- `info@agent-ia.mx` family is a seeded DEMO family (`seed_demo_family.py`, additive + scoped) — not Juan's real family.
