# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Family Task Manager** — gamified family chore/task app with points, rewards, and consequences. Multi-tenant by design (each family is fully isolated). Live at https://gcp-family.agent-ia.mx.

**Stack**: Python 3.12 + FastAPI (backend) · Astro 5 + Tailwind CSS v4 (frontend) · PostgreSQL 15 + Redis 7 · Docker Compose · Anthropic Claude API (receipt scanner)

**Environments**:
- Local (dev): frontend `http://localhost:3003`, backend `http://localhost:8003/docs` — secrets in `.env`
- **Production (GCP)**: `https://gcp-family.agent-ia.mx` + `https://api-gcp-family.agent-ia.mx` (Cloudflare Tunnel `gcp-family`). VM `family-app` (e2-medium) in project `family-prod`, zone `us-central1-a`. App at `/home/jc/family-task-manager/`, compose file `docker-compose.gcp.yml`, secrets in `.env` on host. Deploy via `./scripts/deploy-gcp.sh`. Canonical GCP env config (project, zone, instance name) lives in `.deploy.gcp.env` at the repo root and is sourced by every `scripts/*.sh` helper.
- **On-prem (10.1.0.99) — DECOMMISSIONED 2026-05-23**: was `https://family.agent-ia.mx` under rootless podman. systemd unit disabled, containers stopped. DB dump retained at `/mnt/nvme/docker-prod/family-task-manager/backups/pre-gig-photo-*.sql`. Repo + volumes preserved in case of rollback. Do NOT redeploy without a full reassessment — the canonical DB now lives on the GCP VM.

**Production deployment**: `./scripts/deploy-gcp.sh` is the canonical path — rsyncs source, builds images, brings the stack up, runs alembic migrations, smoke-checks the public endpoints. Local `docker-compose.yml` is for dev only.

> Note: There is NO `docker-compose.onprem.yml` or `docker-compose.production.yml`. There is NO `start-onprem.sh`. There is NO `.github/workflows/`. The legacy `deploy-prod.sh` is kept for archival only — do not run it.

---

## Production runtime — GCP VM `family-app`

Standard Docker CE under user `jc`. e2-medium in `family-prod` / `us-central1-a`. All AI traffic routes through the on-prem LiteLLM proxy at `https://litellm.agent-ia.mx`. No Vault — secrets live in `.env` on the VM at `/home/jc/family-task-manager/.env` (template at `.env.gcp.example`). The project/zone/instance identifiers used by every `scripts/*.sh` helper are sourced from `.deploy.gcp.env` at the repo root — update them there, not in individual scripts.

**Recovery**: if the instance is ever deleted or otherwise needs to be recreated (deploy script reports `VM ... is not RUNNING` and `gcloud compute instances list` shows it missing), recreate via:

```bash
gcloud --account=info@agent-ia.mx --project=family-prod \
    compute instances create family-app \
    --zone=us-central1-a --machine-type=e2-medium \
    --image-family=debian-12 --image-project=debian-cloud \
    --tags=http-server,https-server --boot-disk-size=30GB
```

Then `./scripts/gcp-bootstrap.sh` → scp .env → `./scripts/deploy-gcp.sh` → restore DB from the most recent dump.

**Cloudflare Tunnel `gcp-family`** routes the public hostnames. Configured in the Zero Trust dashboard (NOT in `cloudflared` config.yaml):
- `gcp-family.agent-ia.mx` → `http://frontend:3000`
- `api-gcp-family.agent-ia.mx` → `http://backend:8000`

The on-prem `family.agent-ia.mx` apex is **retired**. Canonical URL is `gcp-family.agent-ia.mx`.

### Bootstrap (one-time per VM)

```bash
./scripts/gcp-bootstrap.sh         # installs docker + compose-plugin, creates app dir
gcloud compute scp .env.gcp.example jc@family-app:/home/jc/family-task-manager/.env --zone=us-central1-a
# Fill in secrets in the VM's .env (or scp a complete one from local), then:
./scripts/deploy-gcp.sh
```

### Common ops

```bash
# Status
gcloud --account=info@agent-ia.mx --project=family-prod \
  compute ssh family-app --zone=us-central1-a \
  --command='cd /home/jc/family-task-manager && sudo docker compose --env-file .env -f docker-compose.gcp.yml ps'

# Logs (backend)
gcloud --account=info@agent-ia.mx --project=family-prod \
  compute ssh family-app --zone=us-central1-a \
  --command='cd /home/jc/family-task-manager && sudo docker compose --env-file .env -f docker-compose.gcp.yml logs -f backend'

# Quick redeploy (skip backup + cached images)
./scripts/deploy-gcp.sh --skip-backup --skip-build -y

# Run migrations only
gcloud --account=info@agent-ia.mx --project=family-prod \
  compute ssh family-app --zone=us-central1-a \
  --command='cd /home/jc/family-task-manager && sudo docker compose --env-file .env -f docker-compose.gcp.yml exec -T backend alembic upgrade head'

# DB shell
gcloud --account=info@agent-ia.mx --project=family-prod \
  compute ssh family-app --zone=us-central1-a \
  --command='cd /home/jc/family-task-manager && sudo docker compose --env-file .env -f docker-compose.gcp.yml exec -T postgres psql -U familyapp familyapp'
```

### Gig proof uploads volume

Backend persists gig proof images under `/app/uploads/gig-proofs/<uuid>.<ext>`. The volume is bind-mounted from the host (`receipt_uploads`). Backend mounts `/uploads/*` as FastAPI `StaticFiles`. The frontend serves them publicly through the Astro proxy at `/uploads/gig-proofs/[file].ts`, which forces cookie-bearer auth before piping bytes from backend.

If a fresh deploy hits `PermissionError: [Errno 13] Permission denied: '/app/uploads/gig-proofs'`, the volume's UID/GID does not match the in-container `appuser` (UID 1000). Fix:

```bash
# Identify volume mountpoint then chown:
sudo chown -R 1000:1000 $(docker volume inspect family-task-manager_receipt_uploads --format '{{.Mountpoint}}')
sudo docker compose --env-file .env -f docker-compose.gcp.yml restart backend
```

### DB backup + restore

Backups under `/home/jc/family-task-manager/backups/` (created by `./scripts/deploy-gcp.sh` unless `--skip-backup`). To dump on demand:

```bash
gcloud --account=info@agent-ia.mx --project=family-prod \
  compute ssh family-app --zone=us-central1-a \
  --command='cd /home/jc/family-task-manager && sudo docker compose --env-file .env -f docker-compose.gcp.yml exec -T postgres pg_dump -U familyapp familyapp' > /tmp/family-backup.sql
```

Restore (after stopping or with empty target DB):

```bash
gcloud compute scp /tmp/family-backup.sql jc@family-app:/tmp/restore.sql --zone=us-central1-a
gcloud --account=info@agent-ia.mx --project=family-prod \
  compute ssh family-app --zone=us-central1-a \
  --command='cd /home/jc/family-task-manager && sudo docker cp /tmp/restore.sql gcp_family_db:/tmp/restore.sql && sudo docker compose --env-file .env -f docker-compose.gcp.yml exec -T postgres bash -c "psql -U \$POSTGRES_USER \$POSTGRES_DB < /tmp/restore.sql"'
```

### Decommissioned on-prem (10.1.0.99) — DO NOT RESURRECT WITHOUT REVIEW

The on-prem stack is stopped (`systemctl --user disable --now family-task-manager.service`, ran 2026-05-23). Containers and volumes still live at `/mnt/nvme/docker-prod/family-task-manager/` in case a quick rollback is ever needed, but the canonical DB has moved to GCP. The host's other services (`homeassistant.service`, `cloudflared.service`, host-wide LiteLLM proxy at `litellm.agent-ia.mx`) continue to run as before — only the family stack is down.

---

## Common Commands

### Production / GCP (Docker CE, as `jc` via gcloud)

```bash
# Full deploy (rsync + build + up + migrate)
./scripts/deploy-gcp.sh -y

# Quick redeploy
./scripts/deploy-gcp.sh --skip-backup --skip-build -y

# Status / logs (helpers — see Common Ops above for full incantations)
gcloud --account=info@agent-ia.mx --project=family-prod \
  compute ssh family-app --zone=us-central1-a --command='sudo docker ps'

# Run backend tests inside the running container
gcloud --account=info@agent-ia.mx --project=family-prod \
  compute ssh family-app --zone=us-central1-a \
  --command='cd /home/jc/family-task-manager && sudo docker compose --env-file .env -f docker-compose.gcp.yml exec -T backend pytest tests/ -v'
```

### Local dev (podman compose)

```bash
podman compose up -d                                          # Start all services
podman compose ps                                             # Status
podman compose logs -f backend                               # Logs

# Tests (run inside container)
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/ -v
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_auth.py -v
podman exec -e PYTHONPATH=/app family_app_backend pytest -k "test_name" -v
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/ --cov=app --cov-report=html

# Migrations
podman exec family_app_backend alembic upgrade head
podman exec family_app_backend alembic revision --autogenerate -m "description"

# Seed demo data
podman exec family_app_backend python /app/seed_data.py
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

### Additional domains (beyond budget/task/gig)

The app has grown well past the budget/task/gig core. These domains are fully wired
(routes + services + models + frontend) and multi-tenant by `family_id`:

| Domain | Routes | Notes |
|--------|--------|-------|
| **Jarvis** (AI copilot) | `/api/jarvis`, `/api/jarvis/schedules` | Parent-facing LLM assistant via LiteLLM (tool-calling + SSE streaming) + cron-driven scheduled prompts. Formerly "Frankie". |
| **Pet** | `/api/pet` | Gamified virtual pet per kid (`kid_pet`, `pup_snapshot`); decays over time, fed by completing work. |
| **Meals** | `/api/meals` | Meal planning + recipe import; syncs to shopping lists. |
| **Shopping** | `/api/shopping` | Family shopping lists; receipt-scan + meal-plan integration. |
| **Calendar** | `/api/calendar` | Family events + AI calendar-image scanner (`calendar_scanner_service`). |
| **Chat / DM** | `/api/chat`, `/api/dm` | Family group chat (reactions, read state) + direct messages. |
| **Kiosk** | `/api/kiosk` | Shared-device kiosk mode (`kiosk_device`). |
| **Analytics** | `/api/analytics` | Family "PUP" snapshots / progress analytics. |
| **Consequences / Rewards / Points** | `/api/consequences`, `/api/rewards`, `/api/points-conversion` | Discipline + reward economy on top of the points system. |

A 2026-06-04 production-readiness audit lives in `docs/audit/2026-06-04/` (findings,
remediation plan, and what's been fixed across Tracks A–D).

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
| `docker-compose.yml` | Local dev compose (all services) |
| `docker-compose.gcp.yml` | Production compose (used by `./scripts/deploy-gcp.sh`) |
| `docker-compose.stage.yml` | Staging compose (override) |
| `scripts/deploy-gcp.sh` | Canonical production deploy script (target: GCP VM) |
| `scripts/gcp-bootstrap.sh` | First-time VM setup (Docker CE install, app dir) |
| `deploy-prod.sh` | **LEGACY** — old on-prem path, do not run |

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

- **968+ tests collected**, 0 failures (suite fully greened in PR #36)
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
