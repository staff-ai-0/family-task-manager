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

The **only** sanctioned exception is `app/services/admin/`, reached exclusively
through `require_superadmin`. Never relax `family_id` filtering anywhere else,
and never use `verify_family_id` or `get_family_user` in an admin route — both
compare against the caller's own `family_id`.

### Clean architecture layers

```
Routes (HTTP only) → Services (business logic) → SQLAlchemy models (DB)
```

Routes must not contain business logic. Services own domain rules. Use `base_service.py` for common CRUD.

### Authentication

- JWT tokens contain `user_id`, `role`, `family_id`; access+refresh pair in httpOnly cookies
- **Auth is stateless — Redis is NOT in the login path.** Nothing in `dependencies.py`, `auth_service.py` or `security.py` touches Redis; a session is the JWT pair plus `users.token_version` (bumped by logout-everywhere, password reset, soft-delete, admin action). Redis carries chat/DM pub-sub, the scheduler lock, and caches (member prefs, FX, receipt scanner) — losing it degrades realtime and caches, it does not log anyone out.
- Roles: `PARENT` (full access), `TEEN` (extended), `CHILD` (limited)
- Prefer the `require_parent_role` dependency (`app/core/dependencies.py`) over inline role checks
- Google OAuth accepts multiple client IDs: `GOOGLE_CLIENT_ID` (web) plus `GOOGLE_CLIENT_IDS` (comma list, for native iOS/Android client IDs under the same Cloud project). `GoogleOAuthService.verify_google_token` skips library-level `aud` validation and checks against the union manually (`backend/app/services/google_oauth_service.py`).

### JSON serialization for strict clients (iOS Swift, Android Kotlin)

SQLAlchemy `func.sum` over a `BigInteger` column returns a `Decimal` under asyncpg. Pydantic v2 serializes `Decimal` as a JSON **string** even when the schema field is typed `int` — strict-decoding mobile clients then fail with `Expected Int but found String`. **Always cast aggregated numeric values to `int()` before assigning to a Pydantic field.** Canonical pattern: `backend/app/api/routes/budget/accounts.py` (the `list_accounts` enrichment loop).

### API structure

All routes prefixed `/api/`. Key route groups:
- `/api/auth/` — register, login, OAuth callbacks
- `/api/task-templates/` + `/api/task-assignments/` — the task system (the pre-2026 legacy `/api/tasks` system was fully removed 2026-07-16: code, model, and — via the `drop_legacy_tasks` migration — its table). Parent review is **graded**: `ApprovalDecision.grade` = `full` / `partial` (1–99%, default 50) / `missed`; point awards scale by the grade (integer half-up) and `approval_notes` surfaces to the kid. Partial is rejected on collaboration gigs (pot conservation). **Wording rule**: this review queue is chores + bonus tasks (points) — user-facing copy says "task/tarea"; the word "gig" is reserved for the cash gig board (`gig_claim_*` keys).
- `/api/rewards/`, `/api/consequences/`, `/api/points-conversion/`
- `/api/subscriptions/` — plan management, PayPal integration
- `/api/budget/` — 23 sub-route groups (see Budget System below)
- Full domain list: see "Additional domains" table below

### Budget system

Fully native to PostgreSQL (the external "Actual Budget" service was decommissioned in Phase 10; the old `/api/sync/*` 410 stubs were removed 2026-07-16). Never re-introduce external budget dependencies.

**Account list endpoint includes computed balance**: `GET /api/budget/accounts/` enriches every row with `balance_cents` + `cleared_balance_cents` (both `Optional[int]`, populated only by list endpoints — null on POST/PUT responses). Avoids N+1 calls from clients. `starting_balance` is the seed value at account creation; when non-zero `AccountService.create` auto-inserts a synthetic "Starting Balance" transaction so the computed balance is correct from day one.

**16 budget models** in `backend/app/models/budget.py`:
- Core: `BudgetCategoryGroup`, `BudgetCategory`, `BudgetAccount`, `BudgetPayee`, `BudgetTransaction`, `BudgetAllocation` (+ transaction items/splits)
- Rules & Goals: `BudgetCategorizationRule`, `BudgetGoal`
- Scheduling: `BudgetRecurringTransaction`
- Organization: `BudgetSavedFilter`, `BudgetTag`, `BudgetTransactionTag`
- Analytics: `BudgetCustomReport`
- HITL: `BudgetReceiptDraft` — low-confidence scans pending human review

(The dead `BudgetSyncState` sync-tracking table for the decommissioned external "Actual Budget" sync engine was dropped 2026-07-22 — see `drop_budget_sync_state` migration.)

**23 budget sub-routes** (`backend/app/api/routes/budget/`):
- Core CRUD: `categories`, `accounts`, `transactions`, `allocations`, `payees`, `transfers`
- Time: `month` (single month view), `months` (month locking)
- Rules: `categorization-rules` · Goals: `goals` · Scheduling: `recurring-transactions`
- Data: `recycle-bin`, `saved-filters`, `tags`
- HITL: `receipt-drafts` (list pending / approve / reject low-confidence scans)
- Import/Export: `transactions/import/csv`, `transactions/import/file` (OFX/QIF/CAMT), `transactions/scan-receipt` (AI), `export`, `import-backup`
- Analytics: `reports`, `custom-reports` · Templates: `allocations/auto-fill` (5 strategies)

**28 budget services** in `backend/app/services/budget/` — one per concern; notable beyond the CRUD set: `a2a_webhook_service` (bank-email-matcher agent intake), `account_matching_service`, `category_ai_service`, `dedup_service`, `duplicate_guard_service`, `transfer_detector`, `transaction_item_service`, `default_categories`.

**Retroactive completion**: a parent can record that a pending/overdue chore was actually done — `POST /api/task-assignments/{id}/mark-done-for-kid` (parent only, note required, 8-week horizon). It awards NOTHING: it sets `COMPLETED` + `approval_status=PENDING` so the task enters the normal graded-review queue and `approve_gig` stays the single place points are credited. `week_of`/`assigned_date` are deliberately preserved, since `_chore_units` and the family cup both scope on `week_of` — credit lands on the week the chore was DUE. The response returns `week_already_paid`: `release_chore_paycheck` is idempotent per (kid, week), so on an already-released week grading credits points but NO cash, and the UI must say so (remedy is `release_chore_paycheck`'s `adjustment_cents`).

### Subscription & premium gating

3-tier plan system (Free / Plus / Pro) with PayPal billing integration (PayPal ONLY — no Stripe, no Mercado Pago).

- Models: `SubscriptionPlan`, `FamilySubscription`, `UsageTracking` in `backend/app/models/subscription.py`
- Feature gating: `backend/app/core/premium.py` — `require_feature()` checks plan limits
- Metered features: `receipt_scan`, `budget_transaction`, `recurring_transaction`, `family_member`, `budget_account`
- Boolean features: `budget_reports`, `budget_goals`, `csv_import`, `ai_features`
- **Every LLM call site must be gated** (`require_feature("ai_features")` or `family_tier_allows`); regression suite `test_ai_gating.py`

**Plan prices have exactly one source**: `backend/app/core/plan_pricing.py`
(`CANONICAL_PRICES`, minor units). `scripts/setup_paypal_plans.py` derives
from it; the `restore_plan_prices` migration carries a FROZEN copy that
`test_plan_pricing_invariants.py` asserts has not drifted; the frontend has
NO copy and renders `—` when a row is missing or priced 0. Never add a
fourth copy — three hand-synced ones is how prod advertised "$0/mes" from
2026-07-16 to 2026-07-31 while `/checkout` returned 501. If prices are ever
re-zeroed again, the remedy is `python -m scripts.restore_plan_prices`
(`--dry-run` to preview) — **not** `alembic upgrade head`, which only fixes
this once: alembic refuses to re-run an already-applied revision, so on a
repeat re-zeroing it reports "already at head" and changes nothing.

`plan_pricing.audit_plan_rows()` detects active paid rows that cannot sell
(zero price, drift from canonical, unwired `paypal_plan_id_*`). It backs
TWO consumers: a startup `logger.error` and `GET /api/admin/billing-config`
(red panel on the operator console) — both run against production data but
neither blocks anything. The `deploy-onprem.sh` billing smoke check
(`verify_billing`) is a deliberately INDEPENDENT third check, not a caller
of `audit_plan_rows()`: it re-derives a weaker version of the same rule
in-line against the public `/api/subscriptions/plans` endpoint, which is
the only one of the three that **gates** a deploy on production data (`GET
/api/subscriptions/plans` is what a customer's browser actually receives —
tunnel, serialization, computed `checkout_ready_*` fields included, none of
which an in-process `audit_plan_rows()` call would exercise). Because it
does not import `plan_pricing`, it catches a non-positive price or an
unwired PayPal id but — unlike `audit_plan_rows()` — does **not** catch a
price that has drifted from canonical while staying positive.

**Plan credit (coupons, referrals, operator comps) is ONE mechanism**:
`plan_credit_grants`, written only by `PlanCreditService.grant`. A grant is
`(family_id, source, tier, starts_at, ends_at | NULL = lifetime, revoked_at)`;
`premium.get_family_plan_by_id` floors the family at the highest active
grant's tier, and a higher paid plan always wins. Credit is INTERNAL — no
PayPal object is created and no PayPal-linked column is written, so the
nightly reconcile sweep cannot erase it. Windows are ADDITIVE **at or above
the granted tier**: a grant starts at the first moment the family is not
already entitled at `>=` its own tier — it queues behind every unrevoked
*dated* grant of tier `>=` its own (**including ones that have not started
yet**, which is what makes stacking additive; lifetime grants are NOT
anchors, so a code redeemed under lifetime Pro burns in parallel for
nothing), and defers behind a live paid period only when the paid tier is
`>=` the granted tier **and** that subscription is genuinely entitling —
a `payment_failed` sub past its grace window is treated as free here, the
same as in `premium`, because the sweep that later fixes the *status* never
revisits a `starts_at` already written. So two 30-day Plus codes give 60
days, a
payer's free month begins after the time they already bought, but a Pro comp
handed to a Plus subscriber starts NOW rather than waiting out a plan it
outranks. Operator comps therefore STACK; the old absolute "Plus until X"
overwrite is gone. `families.referral_bonus_until` was dropped in the
`migrate_referral_bonus_to_grants` migration — do not reintroduce a
per-family credit column.

`coupons` is an operator catalog, cross-tenant like `subscription_plans`
(no `family_id`), reached only through `require_superadmin` — except the
redeem path, which looks one code up by exact match and never lists. Every
unusable-code reason returns an identical `404 invalid_or_expired_coupon`
so redeem is not an oracle; only `409 already_redeemed` is distinct. The
one-per-family guard is `UNIQUE(family_id, coupon_id)` at the DB level, and
the redemption cap is enforced by a predicated `UPDATE` (race-free, no
`SELECT … FOR UPDATE`). `coupons.kind` (launch/beta/comp) is a reporting
label with NO behavior — never branch resolution logic on it.

**A credited family still reads as `free` on the API.** A grant never writes
a `FamilySubscription` row, so `GET /api/subscriptions/current` returns its
hardcoded `plan_name: "free"` while `limits` already reflect the credited
tier. The reconciliation is deliberately frontend-side, in
`parent/settings/subscription.astro`: the page floors the DISPLAYED tier by
the highest active credit (header, comparison table, upgrade buttons) while
cancel/period-end stay keyed to the real subscription — a credit has no
PayPal subscription to cancel. Any NEW surface that shows a plan name must
floor it the same way, or it will invite a comped family to pay for what it
already has.

Percent/amount-off coupons are NOT implemented; `discount_percent`,
`discount_amount_cents` and `discount_cycles` are reserved columns for a
phase-2 PayPal plan-override at subscription-create.

### AI Receipt Scanner

Uses Claude Vision via LiteLLM proxy to extract transaction data from receipt photos/PDFs.

- Service: `backend/app/services/budget/receipt_scanner_service.py`
- **The LLM client is built in exactly one place**: `backend/app/core/llm.py` — `get_llm_client()` plus `LLM_TIMEOUT` (5s connect / 60s read) and the `RECEIPT_MODEL` / `CATEGORIZER_MODEL` aliases. Every call site (Jarvis ×2, calendar scanner, recipe importer, proof validator, category AI, receipt scanner) goes through it; never hand-roll `OpenAI(...)` in a service. Tests mock `app.core.llm.OpenAI`, not the service module.
- Endpoint: `POST /api/budget/transactions/scan-receipt` (parent only, premium gated)
- **Frontend is a sheet, not a page**: `frontend/src/components/budget/ReceiptScanSheet.astro`, mounted once by `BudgetShell`, so any budget page can scan without navigating. Open it with `[data-scan-receipt-open]` or a `ftm:scan-receipt` window event; `input.click()` must stay synchronous with the originating gesture (iOS drops a picker opened after an `await`). ONE file input, deliberately **without `capture`** — that attribute pins iOS to the camera, which is why the old page needed separate camera/upload/bulk buttons; `multiple` on the same input drives the bulk path. `/budget/scan-receipt` remains as an addressable landing page (email links, drawer fallback) that just opens the sheet.
- Routes through LiteLLM proxy (`LITELLM_API_BASE` / `LITELLM_API_KEY`) using model alias `claude-haiku`
- PDFs are rasterized to JPEG (first page only, capped at 3000px, quality 85) via PyMuPDF before sending to vision API
- **Original-image persistence** goes through `app/services/storage/receipt_storage.py`, which picks a backend from `RECEIPT_STORAGE_BACKEND`: `local` (default — writes to `UPLOADS_ROOT/receipts`, on the already-backed-up `receipt_uploads` volume) or `gcs` (opt-in, needs real Google credentials). Reads dispatch on the stored path, not on config: `local:`-prefixed keys are local, bare keys are legacy GCS objects. This was GCS-only until 2026-07-27, which meant every on-prem scan silently discarded its image (no ADC in the container, failure swallowed by the best-effort `except`).

**Reading a receipt's items back**: the scan confirm card is not the only view any more. `GET /api/budget/items/` takes `transaction_id` (as well as `normalized_name`) — family-scoped in both cases, since the id is client-supplied. The transaction LIST response carries `item_count` (0 on POST/PUT, same convention as `balance_cents`), which drives the 🧾 marker on rows, and the transaction edit sheet renders a "Receipt items" panel whose rows link to `/budget/items/<normalized_name>`. Note `/budget/transactions/<id>` is NOT a route — only the list page and `/new` exist — so link to `/budget/transactions?tx=<id>` to open the edit sheet.

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
| **Gigs / Cash / Bank** | `/api/gigs`, `/api/cash`, `/api/bank` | Two-currency economy: chores+bonus → points; gig BOARD → cash ($MXN). Family Bank (match/interest/allowance payday sweep). Allowance modes per kid: `flat` · `chore_proportional` (points-weighted) · `chore_gated` · `points_rate` (grade-scaled chore points × `families.point_value_cents`, parent-released; converted points deducted). Paycheck math is grade-aware (`_chore_units`: points×pct integer units). |
| **Consequences / Rewards / Points** | `/api/consequences`, `/api/rewards`, `/api/points-conversion` | Discipline + reward economy on top of the points system. |
| **Admin** (operator console) | `/api/admin` | Cross-tenant operator surface: family directory, per-family support views, ten bounded write actions, append-only `operator_audit_log`. Gated by `require_superadmin` — `users.is_superadmin` **AND** `SUPERADMIN_EMAILS`, 404 on failure. Frontend at `/admin/*` behind a Cloudflare Access path policy. Metadata only: no message bodies, no images. See `docs/superpowers/specs/2026-07-26-super-admin-dashboard-design.md`. |

Production-readiness audits live in `docs/audit/` (2026-06-04 techdebt, 2026-07-02 UX, 2026-07-07 launch gaps).

### Onboarding tours

Two layers, with separate state:

- **Welcome tour** (driver.js) — one pass over the bottom nav, parent and kid variants in `buildTour`. State: the `users.completed_welcome_tour` boolean, acked at `POST /api/auth/ack-tour`.
- **Module tours** — per-module walkthroughs built by `buildModuleTour` (`frontend/src/lib/tourSteps.ts`): `budget-parent`, `gigs-parent`, `gigs-kid`, `chores-parent`, `rewards-kid`. `ModuleTour.astro` auto-runs one on the user's first visit to its page, suppressed while the welcome tour is running. State: `users.completed_tours` (JSONB list) via `POST /api/families/onboarding/tours/{id}/complete` — not parent-gated, since two tours are kid-facing. Replay hub (`TourHub.astro`) sits above the guide on `/help` + `/ayuda`; a card links to `<page>?tour=<id>`, which overrides both the DB flag and the localStorage guard.
- **Tour ids live in two places and must stay in sync**: `MODULE_TOUR_IDS` in `tourSteps.ts` and `TOUR_IDS` in `backend/app/api/routes/onboarding.py`. An id missing from the backend allowlist gets a 422 nobody sees, so that tour re-runs on every visit forever.
- Steps point at `[data-tour="…"]` anchors. `runTour` drops steps whose element is missing or invisible, so a tour degrades instead of spotlighting empty space — which also means a renamed anchor fails silently.

### Per-family module registry

`families.enabled_modules` (JSONB, NULL = all on) lets a family switch optional surfaces off: `meals`, `shopping`, `calendar`, `pet`, `chat`, `budget`, `gigs` (`backend/app/core/modules.py`). Core (tasks/rewards/consequences/points) is never togglable. Gating is UX-only: `/auth/me` denormalizes the list, BottomNav/MoreSheet filter links, and `frontend/src/middleware.ts` bounces deep links into a disabled module to `/dashboard?module_off=1` — backend APIs stay live. Toggles + starter presets live in parent settings → family ("Módulos").

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

Always use Alembic — never modify the DB schema with raw SQL. Test migrations locally before production. Single-head chain (107 revisions as of 2026-07-22); CI exercises upgrade → downgrade -1 → upgrade.

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
