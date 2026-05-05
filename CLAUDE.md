# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Family Task Manager** — gamified family chore/task app with points, rewards, and consequences. Multi-tenant by design (each family is fully isolated). Live at https://family.agent-ia.mx.

**Stack**: Python 3.12 + FastAPI (backend) · Astro 5 + Tailwind CSS v4 (frontend) · PostgreSQL 15 + Redis 7 · Docker Compose · Anthropic Claude API (receipt scanner)

**Environments**:
- Local (dev): frontend `http://localhost:3003`, backend `http://localhost:8003/docs` — secrets in `.env`
- Production (10.1.0.99 on-prem, **rootless Podman under user `jc`**): `https://family.agent-ia.mx` (Cloudflare tunnel) — app at `/mnt/nvme/docker-prod/family-task-manager/`, secrets in `.env` on host (Vault env vars currently empty; bootstrap falls back to `.env`)

**Production deployment**: `docker-compose.yml` is prod-ready (`docker-compose.stage.yml` for staging). Preferred restart path is the user-level systemd unit (`systemctl --user restart family-task-manager`), NOT `deploy-prod.sh` — that script invokes `sudo docker compose` which corrupts rootless storage on this host (see "Production runtime" section below).

> Note: There is NO `docker-compose.onprem.yml` or `docker-compose.production.yml`. There is NO `start-onprem.sh`. There is NO `.github/workflows/`. Older docs that referenced these are removed.

---

## Production runtime (10.1.0.99)

**Rootless Podman under user `jc`** — every stack runs as `jc`, not root.
- Storage: `/mnt/nvme/podman-storage` (overridden in `~jc/.config/containers/storage.conf`; same path also set in `/etc/containers/storage.conf` and `/root/.config/containers/storage.conf`)
- Runtime dir: `/run/user/1000/containers`
- Autostart: user-level systemd units in `~jc/.config/systemd/user/`, linger enabled (`loginctl enable-linger jc`)

Active user units: `family-task-manager.service`, `homeassistant.service`, `cloudflared.service`.

### Critical: never `sudo podman` against this host

Both system and root storage configs point at jc's storage + runtime dir. Running `sudo podman` writes those files as root → jc can no longer read its own state → `podman ps` fails with `permission denied`. Recovery:

```bash
sudo chown -hR jc:jc /mnt/nvme/podman-storage
sudo find /run/user/1000 -not -user jc -delete
```

`deploy-prod.sh` invokes `sudo docker compose` (via the podman-docker shim). On this host that is **wrong** — bypass it. Run `podman-compose` directly as `jc`:

```bash
ssh jc@10.1.0.99 'cd /mnt/nvme/docker-prod/family-task-manager && podman-compose up -d'
# preferred — managed by systemd:
ssh jc@10.1.0.99 'systemctl --user restart family-task-manager'
```

### Cloudflared is host-wide, not bundled with HA

Tunnel runs standalone at `/mnt/nvme/docker-prod/cloudflared/` with `network_mode: host` and its own `cloudflared.service` user unit. Tunnel ingress is managed remotely via the Cloudflare zero-trust dashboard (`TUNNEL_TOKEN` env activates remote config); the local `config.yaml` is not authoritative.

### Stale netavark rules can break rootless port reachability

Symptom: a rootless service port (e.g. `:3003`) responds on IPv6 (`localhost`, `::1`) but returns "Connection refused" on IPv4 (`127.0.0.1`, `10.1.0.99`). Cause: stale `nv_*_dnat` chain left in the `inet netavark` nftables table from a prior `sudo podman` invocation. Fix:

```bash
sudo nft delete table inet netavark
sudo podman network reload --all
```

---

## Common Commands

### Production / on-prem (rootless podman, as `jc`)

```bash
# Status / logs
ssh jc@10.1.0.99 'podman ps'
ssh jc@10.1.0.99 'podman logs -f family_app_backend'
ssh jc@10.1.0.99 'sudo journalctl CONTAINER_NAME=family_app_backend --since "10 min ago"'

# Restart whole family stack (preferred — systemd-managed)
ssh jc@10.1.0.99 'systemctl --user restart family-task-manager'

# Rebuild image after pulling new code
ssh jc@10.1.0.99 'cd /mnt/nvme/docker-prod/family-task-manager && sudo git pull && podman-compose build backend && systemctl --user restart family-task-manager'

# Tests
ssh jc@10.1.0.99 'podman exec -e PYTHONPATH=/app family_app_backend pytest tests/ -v'

# Migrations
ssh jc@10.1.0.99 'podman exec family_app_backend alembic upgrade head'
```

### Local docker-compose dev

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
- Google OAuth accepts multiple client IDs: `GOOGLE_CLIENT_ID` (web) plus `GOOGLE_CLIENT_IDS` (comma list, for native iOS/Android client IDs registered under the same Cloud project). `GoogleOAuthService.verify_google_token` skips library-level `aud` validation and checks against the union manually (`backend/app/services/google_oauth_service.py:49-77`).

### JSON serialization for strict clients (iOS Swift, Android Kotlin)

SQLAlchemy `func.sum` over a `BigInteger` column returns a `Decimal` under asyncpg. Pydantic v2 serializes `Decimal` as a JSON **string** even when the schema field is typed `int` — strict-decoding mobile clients then fail with `Expected Int but found String`. **Always cast aggregated numeric values to `int()` before assigning to a Pydantic field.** Canonical pattern: `backend/app/api/routes/budget/accounts.py` (the `list_accounts` enrichment loop).

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

**Account list endpoint includes computed balance**: `GET /api/budget/accounts/` enriches every row with `balance_cents` + `cleared_balance_cents` (both `Optional[int]`, populated only by list endpoints — null on POST/PUT responses). Avoids N+1 calls from clients. `starting_balance` is the seed value at account creation; when non-zero `AccountService.create` auto-inserts a synthetic "Starting Balance" transaction so the computed balance is correct from day one.

**15 budget models** in `backend/app/models/budget.py`:
- Core: `BudgetCategoryGroup`, `BudgetCategory`, `BudgetAccount`, `BudgetPayee`, `BudgetTransaction`, `BudgetAllocation`
- Rules & Goals: `BudgetCategorizationRule`, `BudgetGoal`
- Scheduling: `BudgetRecurringTransaction`
- Organization: `BudgetSavedFilter`, `BudgetTag`, `BudgetTransactionTag`
- Analytics: `BudgetCustomReport`
- HITL: `BudgetReceiptDraft` — low-confidence scans pending human review
- Sync (legacy): `BudgetSyncState`

**18 budget sub-routes** (`/api/budget/`):
- Core CRUD: `categories`, `accounts`, `transactions`, `allocations`, `payees`, `transfers`
- Time: `month` (single month view), `months` (month locking)
- Rules: `categorization-rules`
- Goals: `goals`
- Scheduling: `recurring-transactions`
- Data: `recycle-bin`, `saved-filters`, `tags`
- HITL: `receipt-drafts` (list pending / approve / reject low-confidence scans)
- Import/Export: `transactions/import/csv`, `transactions/import/file` (OFX/QIF/CAMT), `transactions/scan-receipt` (AI), `export`, `import-backup`
- Analytics: `reports`, `custom-reports`
- Templates: `allocations/auto-fill` (5 strategies)

**20 budget services** in `backend/app/services/budget/`:
`account`, `allocation`, `categorization_rule`, `category`, `csv_import`, `custom_report`, `export`, `file_import`, `goal`, `month_locking`, `payee`, `receipt_draft`, `receipt_scanner`, `recurring_transaction`, `recycle_bin`, `report`, `saved_filter`, `tag`, `transaction`, `transfer`

### Subscription & premium gating

3-tier plan system (Free / Plus / Pro) with PayPal billing integration.

- Models: `SubscriptionPlan`, `FamilySubscription`, `UsageTracking` in `backend/app/models/subscription.py`
- Feature gating: `backend/app/core/premium.py` — `require_feature()` checks plan limits
- Metered features: `receipt_scan`, `budget_transaction`, `recurring_transaction`, `family_member`, `budget_account`
- Boolean features: `budget_reports`, `budget_goals`, `csv_import`, `ai_features`

### AI Receipt Scanner

Uses Claude Vision via LiteLLM proxy to extract transaction data from receipt photos/PDFs.

- Service: `backend/app/services/budget/receipt_scanner_service.py`
- Endpoint: `POST /api/budget/transactions/scan-receipt` (parent only, premium gated)
- Frontend: `/budget/scan-receipt` (camera capture + file upload + drag-drop; accepts JPEG/PNG/WebP/PDF)
- Routes through LiteLLM proxy (`LITELLM_API_BASE` / `LITELLM_API_KEY`) using model alias `claude-haiku`
- PDFs are rasterized to JPEG (first page only, capped at 3000px, quality 85) via PyMuPDF before sending to vision API

### HITL Receipt Review Queue

Low-confidence scans (<30% or no detectable total) create a `BudgetReceiptDraft` record instead of being discarded.

- Model: `BudgetReceiptDraft` in `backend/app/models/budget.py`
- Service: `backend/app/services/budget/receipt_draft_service.py`
- Endpoints: `GET/POST/DELETE /api/budget/receipt-drafts/` (parent only)
- Frontend: `/budget/receipt-drafts` — review queue with pre-filled editable form per draft
- Nav badge: red dot on clipboard icon in `BudgetNavNew` shows pending count on all budget pages

### Frontend (Astro 5)

Pages live in `frontend/src/pages/`. Routing is file-based. All server-side API calls go to `http://backend:8000` (internal Docker network). Auth state managed via cookies + Astro middleware (`frontend/src/middleware.ts`).

Key frontend pages:
- `/budget/` — main budget dashboard
- `/budget/transactions` — transaction list with filters
- `/budget/scan-receipt` — AI receipt scanner (JPEG/PNG/WebP/PDF)
- `/budget/receipt-drafts` — HITL review queue for low-confidence scans
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
| `backend/app/models/budget.py` | All 15 budget tables |
| `backend/app/models/subscription.py` | Subscription plans, family subscriptions, usage tracking |
| `backend/app/services/budget/receipt_scanner_service.py` | Claude Vision receipt scanning |
| `backend/app/services/budget/file_import_service.py` | OFX/QIF/CAMT parsers |
| `backend/app/services/budget/export_service.py` | Budget export/import as ZIP |
| `backend/tests/conftest.py` | Test fixtures, test DB setup |
| `frontend/src/middleware.ts` | Auth/session middleware for Astro SSR |
| `docker-compose.yml` | Local dev + on-prem compose (all services, prod-ready) |
| `docker-compose.stage.yml` | Staging compose (override) |
| `deploy-prod.sh` | Canonical on-prem deploy script (target: 10.1.0.99) |

---

## Environment variables

Key env vars (set in `.env` or compose file). In production, secrets come from Vault (`secret/family-task-manager/prod`):

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

## Reference data (prod)

- Real user: `juan.mtz79@gmail.com` (PARENT, family_id `1998e48d-2ef0-48b6-a437-cbb730ae935c`)
- ~60 budget transactions imported from bank statements + receipts (May 2026 batch); 17 accounts including duplicates of card variants (e.g. `Mastercard **9222` and `Mastercard **9222 (USD)` for mixed-currency holdings)
