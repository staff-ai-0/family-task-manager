# Super-Admin Dashboard — Phase 0+1: Foundation + Support Console

**Date:** 2026-07-26
**Status:** Design approved, pending implementation plan
**Scope:** Phase 0 (admin foundation) + Phase 1 (support console) of a 6-phase program

---

## 1. Context

Family Task Manager is multi-tenant: every family is fully isolated by `family_id`, enforced
in `BaseFamilyService` and in every route dependency. There is currently **no platform-level
role of any kind** — `UserRole` is `PARENT | TEEN | CHILD` (`backend/app/models/user.py:24-29`).

The only cross-tenant surfaces that exist today are `GET /metrics` (8 Prometheus gauges,
`backend/app/api/routes/internal/metrics.py`) and `POST /api/internal/a2a/retry`, both gated by
the shared static `INTERNAL_API_TOKEN`.

Public launch is imminent. When a stranger emails "my kid's points vanished", there is no way to
answer without SSH-ing to 10.1.0.91 and running psql. This program builds that capability.

### Program decomposition

| # | Sub-project | Depends on |
|---|---|---|
| **0** | Admin foundation — identity, authz, audit log, admin shell, family directory | — |
| **1** | Support console — per-family read views + operator actions | 0 |
| 2 | System health & cost — sweep history, error feed, LLM spend | 0 |
| 3 | Business & growth — funnels, MRR movement, churn, adoption | 0 |
| 4 | Moderation & trust — cross-tenant content review, abuse handling | 0 |
| 5 | AI support — 5a customer help chat · 5b admin triage copilot · 5c inbox triage | 0, 1 |

**This document specs 0+1 only.** They are one spec because the foundation is unverifiable
without a first consumer, and building it blind guarantees rework.

### Decisions taken during design

| Decision | Choice | Rationale |
|---|---|---|
| Access gating | `is_superadmin` flag **AND** env allowlist, behind Cloudflare Access | Neither a DB compromise nor an env change alone is sufficient |
| Admin location | `/admin/*` route group on `family.agent-ia.mx` | Auth cookies are host-only (§3.3) |
| Support depth | Read-only views + fixed operator-action menu | No arbitrary editing; bounded audit surface |
| Private content | **Excluded from Phase 1** | Minors' photos and chat wait for Phase 4's consent/redaction design |
| Impersonation | **Not built** | An impersonated session can do anything a parent can |
| Points/cash adjustments | **Deferred to Phase 1.5** | Actor-attribution problem (§9.1) deserves its own spec |
| Suspend family | Make `families.is_active` genuinely enforced | It is inert today (§9.2) |
| New instrumentation | `users.last_seen_at` only | Highest-leverage gap; history missed cannot be backfilled |

---

## 2. Goals and non-goals

### Goals

1. A single authenticated surface where the operator can find any family and understand its state.
2. A bounded set of safe write actions covering the support cases that will actually arrive.
3. Every operator action recorded in an append-only audit log, in the same transaction as the mutation.
4. Zero weakening of the existing multi-tenant isolation guarantees for non-admin code paths.
5. Begin recording `last_seen_at` before launch, so retention history exists later.

### Non-goals (Phase 1)

- Reading message bodies, DMs, chat, gig proof photos, or receipt images.
- Impersonation / "view as".
- Arbitrary CRUD or a generic table browser.
- Time-series analytics, churn, cohort revenue, per-family AI cost — those need data that does
  not exist yet (Phases 2–3).
- Any moderation queue. There is currently **zero inbound abuse signal** in the app.

---

## 3. Architecture

### 3.1 Identity and authorization

Add to `backend/app/models/user.py`:

```python
is_superadmin = Column(Boolean, nullable=False, default=False, server_default="false")
```

Add to `backend/app/core/config.py`:

```python
SUPERADMIN_EMAILS: str = ""   # comma-separated; parsed to a frozenset property
```

Add to `backend/app/core/dependencies.py`, mirroring the sync shape of `require_parent_role`
(`dependencies.py:58`):

```python
def require_superadmin(current_user: User = Depends(get_current_user)) -> User:
    """Platform operator. Requires BOTH the DB flag and the env allowlist."""
    if not current_user.is_superadmin:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if current_user.email.lower() not in settings.superadmin_emails_set:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return current_user
```

**Both conditions are required.** The DB flag alone would mean a SQL-injection or a stolen DB
dump could mint an operator. The env allowlist alone would mean any account matching a listed
email inherits platform powers, including one created by an attacker who controls that mailbox.

**404, not 403**, for every rejection — on both pages and API. A 403 confirms the surface exists.

Granting the flag is a deliberate out-of-band act: a one-off SQL `UPDATE users SET is_superadmin
= true WHERE email = …` on the prod host, paired with an `.env` edit and a container restart.
There is intentionally **no UI to grant superadmin**. Bootstrapping is documented in
`docs/DEPLOYMENT.md`, not automated.

### 3.2 Route surface

New router mounted at `/api/admin`, registered in `backend/app/main.py`.

Every route depends on `require_superadmin`. Family-targeted routes take `family_id` as an
explicit **path parameter** and must **never** use `verify_family_id` (`dependencies.py:198`) or
`get_family_user` (`:163`) — both hard-compare against `current_user.family_id` and would reject
every admin request.

Heavy aggregate reads open a short-lived session:

```python
async with AsyncSessionLocal() as session:
    ...
```

not `Depends(get_db)`. This follows `internal/metrics.py` and avoids re-introducing the pooled-
session exhaustion that caused the SSE 502 incident.

### 3.3 Frontend placement

`/admin/*` is a **route group inside the existing Astro app**, not a separate app or hostname.

The deciding constraint: `buildCookie()` in `frontend/src/lib/auth-cookies.ts` emits no `Domain=`
attribute, so `access_token` / `refresh_token` are host-only. A second hostname receives no
session at all. Making one work would require either widening the cookie to `Domain=.agent-ia.mx`
— broadening blast radius to every subdomain and touching `auth-cookies.ts`, `login.ts`,
`oauth/google.ts`, `logout.ts`, and the middleware refresh path — or building a parallel auth
story end to end. Additionally the prod CSRF allowlist is hardcoded (`middleware.ts:168`),
`astro.config.mjs` pins `site` and `server.allowedHosts` to the same literal, and backend CORS
reads `ALLOWED_ORIGINS` from `.env`.

A route group is protected by default: `middleware.ts:182-281` is default-deny — an unknown page
path with no token redirects to `/login`.

**Cloudflare Access is applied as a path policy on `family.agent-ia.mx/admin*`**, not a hostname
policy. Same protection, none of the auth surgery.

New frontend files:

- `frontend/src/components/ui/AdminShell.astro` — wraps `Layout.astro` **directly**. Precedent:
  `GuideShell.astro`. Explicitly **not** `PageLayout` or `BudgetShell`, whose `BottomNav` is
  hard-wired with no opt-out prop and fires four backend calls per render.
- `frontend/src/pages/api/admin/[...path].ts` — copied verbatim from `pages/api/budget/[...path].ts`.
  Keep `url.pathname` (not `params.path` — trailing-slash → 307 → 502), `redirect: "manual"`,
  cookie→Bearer injection, and `tryRefreshFor401`.

Middleware gains an explicit `/admin` branch that 404s any authenticated non-superadmin. This
requires one backend change outside the admin router: `GET /api/auth/me` must include
`is_superadmin` in its response (the same denormalization pattern `enabled_modules` already
uses). The middleware check is a UX guard only — the backend's `require_superadmin` is the real
boundary, and every `/api/admin/*` call is independently authorized.

Constraints carried into implementation:

- **No charting or data-grid library exists.** `package.json` has six deps (`@astrojs/node`,
  `@tailwindcss/vite`, `astro`, `driver.js`, `mermaid`, `tailwindcss`), and the prod CSP
  (`script-src 'self' 'unsafe-inline'`, `connect-src 'self'`) forbids CDN scripts. Tables,
  pagination, and any sparkline are hand-rolled. Phase 1 uses **no charts at all** — numbers and
  tables only.
- **No wide-viewport precedent.** Every existing shell caps at `max-w-md md:max-w-4xl lg:max-w-6xl`.
  `AdminShell` defines its own wider container and a restrained variant of the brand tokens
  (reuse `brand-*`, `--shadow-card`, `.num` tabular-nums; see `docs/design-tokens.md`).
- **Admin copy is EN-only**, in a page-local dict. Do not add keys to the 1090-line,
  family-copy-scoped `frontend/src/lib/i18n.ts`.

### 3.4 Service layer

Two new modules under `backend/app/services/admin/`:

- `admin_lookup_service.py` — family/user search and directory listing.
- `admin_read_service.py` — the per-family aggregate reads backing the detail tabs.

These are **dedicated cross-tenant readers**. `BaseFamilyService` is not modified and its
`family_id` filters are not relaxed — doing so would silently widen roughly fifty services.

A third module, `operator_audit_service.py`, wraps audit writes.

### 3.5 Audit log

New table `operator_audit_log`:

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `actor_user_id` | UUID FK → users, NOT NULL | the operator |
| `actor_email` | String(255), NOT NULL | denormalized — survives user deletion |
| `action` | String(64), NOT NULL, indexed | e.g. `family.suspend`, `user.resend_verification` |
| `target_family_id` | UUID, nullable, indexed | **no FK** — must survive family purge |
| `target_user_id` | UUID, nullable | **no FK** — same reason |
| `params` | JSONB, nullable | action inputs, secrets redacted |
| `result` | String(16), NOT NULL | `ok` \| `error` |
| `error` | Text, nullable | |
| `created_at` | TIMESTAMPTZ, NOT NULL, indexed | |

Deliberately **no FK on the target columns**. An audit row must outlive the family it describes;
an FK with CASCADE would erase the record of the deletion at purge time, and one without CASCADE
would block the purge sweep.

`OperatorAuditService.record(...)` is called inside the same transaction as the mutation, so a
failed mutation cannot leave an "ok" audit row and a successful one cannot be unrecorded.

### 3.6 `last_seen_at`

Add `users.last_seen_at TIMESTAMPTZ NULL`. Updated from `get_current_user`, throttled: skip the
write if the stored value is newer than `LAST_SEEN_THROTTLE_MINUTES` (default 15). The write is
best-effort — wrapped so it can never fail a request — and issued as a targeted `UPDATE`, not an
ORM flush of the whole user row.

This is the only new instrumentation in Phase 1. Rationale: it is the sole prerequisite for
DAU/WAU, retention, dormant-tenant detection, and every "is this family alive?" answer in the
support console. Unlike the other gaps, history not recorded during the launch window cannot be
reconstructed later.

---

## 4. Screens

### 4.1 `/admin` — Platform pulse

Numbers and status only, no charts. All from existing columns.

- Families: total, active, pending-purge (`deleted_at IS NOT NULL`)
- Users: total, active, verified, pending approval
- Paying subscriptions and current-state MRR, reported per currency (§8, rule 3)
- **Billing needs-review count** — the highest signal-to-effort tile in the app
- A2A delivery health: by status, oldest pending age, overdue-retry count, dead-letter count (7d)
- Receipt-draft backlog (`status='pending'`)
- Overdue task assignments
- DB / Redis up (reuse `/ready`)

### 4.2 `/admin/families` — Directory

Search by email, family name, family id, or join code. Paginated, hand-rolled.

Columns: name · plan · status · members · created · last activity (`MAX(users.last_seen_at)`) ·
deleted_at.

### 4.3 `/admin/families/:id` — Family detail

Tabs:

| Tab | Contents |
|---|---|
| **Overview** | Family row, timezone, `enabled_modules` (rendered through `effective_modules` semantics), `point_value_cents`, `gig_term`, AI-consent flags, onboarding checklist |
| **Members** | Users: role, email, verified, `approval_status`, oauth provider, active, `last_seen_at` |
| **Economy** | Points balance per kid, cash balances, outstanding paycheck weeks, recent point/cash transactions — amounts and timestamps, no free-text notes |
| **Tasks** | Assignment counts by status; recent approvals with grade and pct |
| **Budget** | Account count and balances, transaction count, pending receipt drafts, recycle-bin count |
| **Billing** | Subscription row, plan, status, PayPal ids, `needs_review` + `review_reason`, `referral_bonus_until`, `payment_failure_at` and grace expiry |
| **Integrations** | `family_a2a_webhooks` + delivery health, `failure_count`, `last_success_at`, `last_error` |
| **Audit** | Operator actions previously taken on this family |

### 4.4 `/admin/billing-review`

Queue over `family_subscriptions.needs_review`, showing `review_reason`. Written by
`subscription_state.mark_for_review` from `subscriptions_webhook.py:180,221` — covers refunds,
reversals, and the failed-cancel double-billing case.

### 4.5 `/admin/deletions`

Families with `deleted_at IS NOT NULL`, showing `purge_after = deleted_at + 30d` and member count.

### 4.6 `/admin/audit`

Global operator audit log, filterable by action, actor, family, date range.

---

## 5. Operator actions

Every action follows: **preview → explicit confirm → audit row → execute → audit result**.
Each reuses an existing service; none writes raw SQL.

| Action | Implementation | Caveat surfaced in UI |
|---|---|---|
| Resend verification email | `EmailService.send_verification_email(db, user, base_url)` (`email_service.py:825`) | `base_url` **must** be `settings.email_link_base`, not `BASE_URL` |
| Trigger password reset | `EmailService.send_password_reset_email` (`:916`) **plus** an explicit `user.token_version` bump | The service does not bump it; the public route does. Omitting it leaves existing sessions alive |
| Comp a month of Plus | Write `families.referral_bonus_until` directly | **Not** `ReferralService._grant_referral_month` — private, does not commit, stacks +30d per call, and is Plus-only |
| Toggle modules | `FamilyService.update_family(db, family_id, FamilyUpdate)` (`family_service.py:130`) | NULL means *all modules on*, not none |
| Deactivate / reactivate user | `AuthService.deactivate_user` (`:472`) / `activate_user` (`:508`) | **Asymmetric**: deactivate bulk-cancels PENDING/CLAIMED/OVERDUE assignments; activate does not restore them |
| Suspend / unsuspend family | `families.is_active` — see §9.2 | Locks out all members immediately |
| Force paycheck release | `BankService.chore_paycheck_preview` → `release_chore_paycheck(...)` (`bank_service.py:778`) | Idempotent per (kid, week). Preview is mandatory before release |
| Undo chore approval | `TaskAssignmentService.patch_assignment` (`:2207`) | **Refuses bonus/gig reversals** (`:2259`) — the UI must say so rather than fail opaquely |
| Restore from budget recycle bin | `RecycleBinService.restore_transaction` / `_account` / `_category` / `_category_group` | |
| Cancel pending family deletion | **New code** (§9.3) | PayPal subs were already cancelled at soft-delete — a restored family must re-subscribe |

**Deferred to Phase 1.5:** points and cash adjustments (§9.1).

---

## 6. Data flow

```
/admin/* page (Astro SSR)
  → same-origin /api/admin/[...path].ts proxy   (cookie → Bearer, refresh on 401)
    → backend /api/admin/*                      (require_superadmin: flag AND allowlist)
      → AdminLookupService / AdminReadService   (explicit family_id argument)
        → short-lived AsyncSessionLocal
```

Mutations additionally write `operator_audit_log` inside the same transaction.

---

## 7. Error handling

| Case | Behaviour |
|---|---|
| Anonymous hits `/admin/*` | Existing default-deny middleware redirects to `/login` |
| Authenticated non-superadmin hits `/admin/*` | **404** page, not 403 |
| Non-superadmin hits `/api/admin/*` | **404**, no body detail |
| Family id not found | 404, indistinguishable from the above |
| Operator action fails | Audit row written with `result='error'` and the real error; UI shows the actual message, no swallowing |
| Mutation succeeds but audit write fails | Whole transaction rolls back. An unaudited mutation is a bug, not a degraded success |
| Aggregate read fails | That tab renders an error state; the rest of the page still loads |

---

## 8. Query correctness rules

These are silent-wrong-answer traps confirmed in the codebase. Every admin query must obey them.

1. **Enum case.** `users.role` and `family_invitations.role` are PG enums storing **uppercase**
   `'PARENT' | 'CHILD' | 'TEEN'`, while the Python enum *values* are lowercase
   (`migrations/versions/2025_12_12_0801-c89db4e73129_initial_schema.py:54`). Comparing to
   `'parent'` returns zero rows silently. `family_subscriptions.status` and
   `users.approval_status` are by contrast plain lowercase VARCHARs.
2. **Soft delete ≠ `is_active`.** Every count filters `families.deleted_at IS NULL` **and**
   `users.deleted_at IS NULL`. `families.deleted_at` is indexed; `users.deleted_at` deliberately
   is not, so filter users via `family_id`. Budget soft-deletes also exist and must be excluded
   (`budget_category_groups/categories/accounts/transactions.deleted_at`).
3. **Entitlement ≠ revenue.** Three paths grant Plus with no money: `referral_bonus_until` in the
   future, `payment_failed` inside the 3-day grace, and the `DEFAULT_FREE_LIMITS` fallback.
   Paying customers are
   `status IN ('active','past_due','payment_failed') AND paypal_subscription_id IS NOT NULL AND plan.name != 'free'`.
   Label the figure **"current-state MRR"** — it is not a time series, and mixed USD+MXN with no
   stored FX rate means it must be reported per currency, not summed.
4. **`enabled_modules` NULL means all modules ON.** Use `app/core/modules.effective_modules`.
5. **`point_transactions` has no `family_id`** — only `user_id`. Family-level points metrics JOIN
   through `users`.
6. **`usage_tracking` only ever increments five keys.** `family_member` and `budget_account` are
   read by `require_feature` but never written — they are permanently zero. Do not build tiles
   for them.
7. **There is no queryable session set.** `SessionMiddleware` is signed-cookie backed
   (`main.py:271-275`) and used only for the OAuth handshake; auth is stateless JWT with
   `token_version` revocation. Do not spec a "who's online" tile. `last_seen_at` is the substitute.
8. **`family_llm_calls_total` counts attempts, per worker, since deploy.** `record_llm_call()`
   fires before the request at all 8 sites, so timeouts and 429s inflate it identically to
   successes, and one Jarvis message can be up to five completions. Label it exactly that, or omit it.
9. **Scheduler health cannot be inferred from `/metrics`.** All 11 sweeps are leader-gated
   (Redis key `ftm:scheduler:leader`); a scrape hits a random worker.

---

## 9. Deliberate design decisions

### 9.1 Points/cash adjustments deferred

`PointsService.create_parent_adjustment` calls `verify_user_in_family` for the **actor**, and
`CashService.adjust` stores `created_by` as an FK to a user. An operator holds no membership in
the target family, so neither can be invoked as-is.

Three options were considered. Attributing the adjustment to one of the family's real parents was
rejected outright: the kid's ledger would then show a change their parent never made — a
falsehood in a record children are explicitly told to trust, and one that makes any dispute
unresolvable. Introducing a nullable/sentinel operator actor is the correct long-term answer but
requires teaching two money services a new concept *and* changing the kid-facing history UI.

**Phase 1 ships neither.** For a points or cash correction, the operator walks the parent through
doing it in their own UI. The nullable-actor design gets its own spec as Phase 1.5.

### 9.2 `families.is_active` made real

`is_active` exists but is enforced in only two places: join-code lookup (`family_service.py:113`)
and registration (`auth_service.py:156`). `authenticate_user` and `get_current_user` never check
it, so a "suspended" family today continues using the entire app.

Phase 1 adds the check to `authenticate_user` and `get_current_user`, returning a distinct error
so the frontend can show a suspension message rather than a generic auth failure. A test asserts
that an existing valid JWT stops working once the family is suspended.

Suspension deliberately does **not** reuse the soft-delete machinery. Conflating "suspended for
abuse" with "user deleted their account" would arm the 30-day purge sweep against a family you
may want to reinstate.

### 9.3 Deletion cancel is new code

Nothing anywhere clears `deleted_at`. The 30-day recovery window is described in
`FamilyDeletionService`'s docstring but was never implemented. Phase 1 adds
`FamilyDeletionService.cancel_deletion(db, *, family_id)` which clears `families.deleted_at` and
the denormalized `users.deleted_at`, guarded so it refuses past the retention window.

The operator UI states plainly that billing is **not** restored: PayPal subscriptions are
cancelled at soft-delete time (`family_deletion_service.py:307-311`), so a restored family must
re-subscribe.

### 9.4 Private content excluded

Gig and task proof photographs are pictures taken by children inside their homes. They live
unencrypted on a podman named volume on a **shared** host (10.1.0.91 also runs school-admin,
medical, platform, vault) and are excluded from `scripts/backup-db.sh`.

A cross-tenant grid of children's home photos is materially worse than the status quo, and
building it correctly requires redaction defaults, per-open reason gating, audit-before-bytes,
and a consent story. That is Phase 4's job. Phase 1 shows counts and timestamps only, and never
renders a message body or an image.

Note also that `families.ai_processing_consent` is narrower than its name: it gates exactly two
paths (proof-photo validation, MCP/Jarvis chat reads) and does **not** gate the calendar document
scanner or the receipt scanner. Do not describe it as blanket "AI consent" in admin copy.

---

## 10. Testing

New file `backend/tests/test_admin_authz.py`:

- **Authorization matrix** — every admin route × {anonymous, child, teen, parent,
  flag-set-but-not-allowlisted, allowlisted-but-flag-unset, both} → only *both* succeeds; all
  others receive 404.
- **Cross-tenant isolation** — an admin read of family A never returns a row belonging to family B.
- **Audit completeness** — every mutating admin route writes exactly one `operator_audit_log` row;
  a forced failure inside the mutation leaves zero audit rows (transaction rollback).
- **Enum case** — a directory search filtered by role returns non-empty results (regression guard
  against the lowercase-comparison trap).
- **Soft delete** — a deleted family is excluded from counts and appears only in `/admin/deletions`.

New file `backend/tests/test_admin_actions.py`:

- Each operator action: happy path, audit row shape, and its documented caveat
  (e.g. `patch_assignment` refusing a bonus reversal, `release_chore_paycheck` idempotency).

New file `backend/tests/test_family_suspension.py`:

- A valid JWT stops authenticating once `families.is_active` is false.
- Unsuspending restores access.

Extend `backend/tests/test_auth.py`:

- `last_seen_at` is written on first authenticated request and **not** rewritten within the
  throttle window.

Frontend: `npm run check` and `astro build` must pass. No new E2E specs in Phase 1 — the admin
surface has no unauthenticated path to exercise and Playwright has no superadmin fixture yet.

CI gates unchanged: `ruff check app`, alembic upgrade/downgrade round-trip, full pytest with the
≥70% coverage gate.

---

## 11. Migrations

Three, in one revision or three sequential ones:

1. `users.is_superadmin` — boolean, not null, server_default false.
2. `users.last_seen_at` — timestamptz, nullable.
3. `operator_audit_log` — new table per §3.5, with indexes on `action`, `target_family_id`,
   `created_at`.

All three are trivially reversible, which matters because CI exercises upgrade → downgrade -1 →
upgrade.

---

## 12. Deployment

- `.env` on 10.1.0.91 gains `SUPERADMIN_EMAILS=juan.mtz79@gmail.com`.
- `.env.example` and `.env.onprem.example` gain the key with an empty default.
- One-off SQL on the prod host sets `is_superadmin = true` for that account.
- A Cloudflare Access application is created for the path `family.agent-ia.mx/admin*`, policy
  restricted to the same email.
- Deploy via `./scripts/deploy-onprem.sh` as usual.

With `SUPERADMIN_EMAILS` empty — the default everywhere including local dev and CI — the admin
surface is unreachable by anyone. It fails closed.

---

## 13. Out of scope, tracked separately

Six defects surfaced during design research. None is caused by this work and none is fixed by it;
each should become its own issue.

1. **`backend/app/api/routes/uploads.py:47`** — proof-image authorization is a URL-string match
   with no role check. Any authenticated family member, **including a CHILD**, can fetch every
   proof photo in their family. *Security.*
2. **`shopping_items` and `kid_pets` have no `family_id`** (`models/shopping.py:55`,
   `models/kid_pet.py:74-81`) — violates the multi-tenant invariant stated in CLAUDE.md today.
3. **`GCS_RECEIPT_BUCKET` is unset on-prem** (absent from both env templates) — committed-
   transaction receipt images are silently not persisted in production.
4. **`families.is_active` is inert** — addressed by §9.2 for the suspend path, but the underlying
   inconsistency predates this work.
5. **`deleted_at` is never cleared** — addressed by §9.3, same note.
6. **`scheduler_lock` fails open on a Redis error** (`scheduler_lock.py:59,67`) — a Redis blip
   makes every worker a leader and runs all 11 crons N times, undetectably. Conversely a dead
   leader pauses every cron until restart. Neither state is observable today.

Items 1–3 are independent bugs. Items 4–6 are partially touched here and fully addressed in
Phase 2 (system health).
