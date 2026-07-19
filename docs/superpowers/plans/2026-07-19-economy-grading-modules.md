# Economy v2 Implementation Plan (grading · points_rate · module registry)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Graded task completion (full/partial/missed + parent feedback), a per-family points→MXN piece-rate allowance mode, and per-family module toggles.

**Architecture:** Extend the existing approval queue (`approve_gig`) with a grade that scales point awards; extend Family Bank's weekly chore-paycheck math to grade-aware integer "units" and add a `points_rate` mode on the existing preview/release flow; add `families.enabled_modules` JSONB consumed by BottomNav/MoreSheet and Astro middleware.

**Tech Stack:** FastAPI + SQLAlchemy async + Alembic · Astro 5 SSR + vanilla script islands · pytest (test DB 5435, bare-metal fallback per memory) · ruff.

**Spec:** `docs/superpowers/specs/2026-07-19-economy-grading-modules-design.md` (incl. the chore_weighted amendment).

## Global Constraints

- Every new table/column additive, nullable or server-defaulted; CI runs upgrade → downgrade -1 → upgrade. Single alembic head (current head: `family_gig_term`).
- All queries filter `family_id` (multi-tenant).
- `ruff check app` zero-tolerance; coverage gate ≥70%.
- New UI strings: inline ES/EN ternaries (existing pattern, no i18n refactor).
- Money math in integer cents; no float. Point/unit math integer.
- Do not touch: gig-board cash pricing, collaboration pot conservation, existing 3 allowance modes' payout values for ungraded weeks.
- Commits per task; PR to main left OPEN (no merge — user reviews).

---

## Phase 1 — Task grading

### Task 1: Grading columns (model + migration)

**Files:**
- Modify: `backend/app/models/task_assignment.py` (after `approval_status` block)
- Create: `backend/migrations/versions/2026_07_19_completion_grade.py`
- Test: migration round-trip runs via existing CI job; local `alembic upgrade head && alembic downgrade -1 && alembic upgrade head`

**Produces:** `TaskAssignment.completion_grade` (`String(10)`, nullable, CHECK in `('full','partial','missed')`), `TaskAssignment.partial_credit_pct` (`SmallInteger`, nullable, CHECK 0–100).

Use `String` + CHECK (not PG enum) — cheaper to extend, matches `allowance_mode` pattern in `kid_bank.py`.

- [ ] Model columns + table_args CHECK constraints
- [ ] Migration `revision='completion_grade', down_revision='family_gig_term'`; `op.add_column` ×2 + `op.create_check_constraint` ×2; downgrade drops both
- [ ] Round-trip locally; commit

### Task 2: Service — grade-aware approve

**Files:**
- Modify: `backend/app/services/task_assignment_service.py:1930-2090` (`approve_gig`)
- Test: `backend/tests/test_task_grading.py` (new)

**Interfaces:**
- `approve_gig(db, assignment_id, family_id, parent_id, approve, notes=None, grade=None, partial_credit_pct=None)`
- Grade resolution: `approve=True` → grade `full` unless `partial` given; `approve=False` → grade `missed` if grade explicitly `'missed'`, else legacy plain reject (grade stays NULL).
- `partial` validation: 1–99, default 50 when grade='partial' and pct None; 422 if grade='partial' on a collaboration template (`template.gig_mode == 'collaboration'`).
- Point scaling: `pct = 100 if grade in (None,'full') else partial_credit_pct`; chore path `pts = round(effective_points * pct / 100)`; non-collab bonus path `pts = round(award_points_per_completer * pct / 100)` — pass into existing award calls (add optional `override_pts` param to `_award_assignment` for the non-collab branch).
- `missed`/reject side-effects unchanged (streak reset, chore re-open, no celebration). Stamp `completion_grade` + `partial_credit_pct` on the row in all graded paths.
- Notification params gain `pct` for partial (`gig_approved` params dict); notes already flow.

- [ ] Failing tests: full=100%, partial 50% rounding (7 pts → 4), partial custom 25, missed → 0 pts + streak reset + chore re-opened, collab+partial → 422, legacy approve/reject unchanged (grade NULL)
- [ ] Implement; run `pytest tests/test_task_grading.py -v` green; commit

### Task 3: API schema + serialization

**Files:**
- Modify: `backend/app/schemas/task_assignment.py:147` (`ApprovalDecision`), response models
- Modify: `backend/app/api/routes/task_assignments.py:423-445` (pass-through), `_assignment_to_detail`
- Test: extend `backend/tests/test_task_grading.py` (route-level via httpx client fixture)

**Produces:** `ApprovalDecision{approve: bool, notes?: str, grade?: Literal['full','partial','missed'], partial_credit_pct?: int}`; assignment detail responses include `completion_grade`, `partial_credit_pct`, `approval_notes`.

- [ ] Failing route tests (approve with grade payload; detail echoes grade+notes)
- [ ] Implement; green; ruff; commit

### Task 4: Frontend — review UI + kid surface

**Files:**
- Modify: parent approvals page (locate: `rg -l "approve" frontend/src/pages/parent/` — expected `approvals.astro`) — replace 2-button approve/reject with: ✓ Completa (full) · ~ Casi (opens 25/50/75 slider, default 50) · ✗ No hecha (missed) + existing notes box; collab rows hide Casi.
- Modify: kid task detail (dashboard assignment card/detail) — grade badge (`Completa` green / `Casi (50%)` amber / `No hecha` red) + parent comment bubble when `approval_notes` present.
- Test: `cd frontend && npm run check && npm run build`

- [ ] Wire fetch payloads (`grade`, `partial_credit_pct`); optimistic mutate() per existing pattern
- [ ] astro check + build clean; commit

---

## Phase 2 — points_rate + point_value_cents + grade-aware payout

### Task 5: `families.point_value_cents` (model + migration + API)

**Files:**
- Modify: `backend/app/models/family.py`
- Create: `backend/migrations/versions/2026_07_19_point_value_cents.py` (`down_revision='completion_grade'`)
- Modify: families settings route/schema (locate PATCH in `backend/app/api/routes/families.py`) — parent-only field, validate 1–100000.
- Test: `backend/tests/test_bank_points_rate.py` (new; settings section)

**Produces:** `Family.point_value_cents` int `nullable=False, default=100, server_default="100"` + CHECK `> 0`; PATCH accepts it; GET family settings returns it.

- [ ] Failing test: PATCH as parent updates, kid 403, 0 rejected
- [ ] Model + migration + route; round-trip; green; commit

### Task 6: Grade-aware `_chore_points` units math

**Files:**
- Modify: `backend/app/services/bank_service.py:370-460` (`_chore_points`, `_chore_paycheck_cents`, `_chore_paycheck_gated`, `chore_paycheck_preview`)
- Test: `backend/tests/test_bank_grading_units.py` (new)

**Interfaces (produces):**
- `_chore_points(db, family_id, user_id, week_monday) -> tuple[int, int]` now returns `(done_units, assigned_units)` where `assigned_units = Σ points×100`, `done_units = Σ points × pct` (pct: 100 full/NULL-approved-completed, `partial_credit_pct` partial, 0 otherwise). Fetch rows `(points, completion_grade, partial_credit_pct, status, approval_status)` for the week and sum in Python — per-kid weekly row counts are tiny.
- `_chore_paycheck_cents(cap_cents, done_units, assigned_units)` / `_chore_paycheck_gated(...)` — same formulas (ratio unchanged by ×100 scale); gated pays iff `done_units >= assigned_units`.
- Preview dict: `done_points = done_units/100` rounded to 1 decimal for display; `pct = round(100*done_units/assigned_units)`.

- [ ] Failing tests: ungraded week identical payout to current behavior (regression: 3 modes × representative weeks), partial 50% task contributes half its points, missed contributes 0, gated blocked by one partial
- [ ] Implement; green; commit

### Task 7: `points_rate` mode (preview + release + deduction)

**Files:**
- Modify: `backend/app/services/bank_service.py` — `ALLOWANCE_MODES += ('points_rate',)`; preview + `release_chore_paycheck` dispatch; sweep filter already excludes non-flat (verify line ~680 `.in_(...)` list gets `points_rate` added so reminder nudges fire but auto-pay does not — mirror proportional handling).
- Modify: `backend/app/services/points_service.py` — add deduction reason constant (e.g. `POINTS_CONVERTED`) if transaction-type enum requires it (inspect `point_transaction.py`; reuse closest existing type if enum is closed — prefer new enum value + migration only if cheap; else description-tagged spend).
- Test: extend `backend/tests/test_bank_points_rate.py`

**Formulas:**
- `projected_cents = done_units * family.point_value_cents // 100` (units already carry ×100 scale: `done_units/100 pts × rate cents/pt`).
- Release: credit via existing `CashService.credit_split_rows(..., CashTransactionType.ALLOWANCE, description="Puntos convertidos (semana ...)")`; then deduct `points_converted = done_units // 100` capped at current balance via PointsService spend/deduct API; idempotency + adjustment_cents behavior identical to proportional.

- [ ] Failing tests: preview math (rate 100 & 250), release credits jars + deducts points + ledger rows, deduction floors at available balance, idempotent 409 on re-release, `allowance_cents` ignored, mode validation accepts `points_rate`
- [ ] Implement; green; ruff; commit

### Task 8: Bank settings UI

**Files:**
- Modify: bank settings frontend (locate: `rg -ln "allowance_mode" frontend/src` — parent bank settings island) — add "Por puntos (tarifa)" option + family-level "Valor del punto (MXN)" input (shown once, saves to families PATCH); preview meter labels for points mode.
- Test: astro check + build

- [ ] Wire + build clean; commit

---

## Phase 3 — Module registry

### Task 9: `families.enabled_modules` + API

**Files:**
- Modify: `backend/app/models/family.py` (JSONB nullable, NULL = all on)
- Create: `backend/migrations/versions/2026_07_19_enabled_modules.py` (`down_revision='point_value_cents'`)
- Modify: families route — PATCH validates subset of `{"meals","shopping","calendar","pet","chat","budget","gigs"}` (list of ENABLED module keys; NULL/absent = all); GET returns effective set.
- Create: `backend/app/core/modules.py` — `TOGGLABLE_MODULES` frozenset + `effective_modules(family) -> set[str]` helper.
- Test: `backend/tests/test_module_registry.py`

- [ ] Failing tests: default NULL → all enabled; PATCH subset persists; unknown key 422; kid 403
- [ ] Implement; round-trip; green; commit

### Task 10: Nav + middleware gating

**Files:**
- Modify: `frontend/src/components/BottomNav.astro`, `frontend/src/components/MoreSheet.astro` — accept `modules` prop (string[] | null), filter links: gigs slot ↔ `gigs`, budget slot ↔ `budget`, meals/shopping/calendar/pet/chat/dm entries per key. Disabled bottom-nav slots fall back (kid: gigs→bank? no — gigs off hides bank too; fill with Pet if enabled else Profile; parent: budget off → Tasks shortcut).
- Modify: `frontend/src/layouts/Layout.astro` (or wherever BottomNav is instantiated — follow `gig_term`'s data path, likely a locals/me fetch) to thread `enabled_modules`.
- Modify: `frontend/src/middleware.ts` — page-route → module map; disabled → 302 `/dashboard?module_off=1`; dashboard shows one-line notice.
- Test: astro check + build; backend tests unaffected.

- [ ] Implement; build clean; commit

### Task 11: Settings toggles + onboarding starter

**Files:**
- Modify: parent settings page (`frontend/src/pages/parent/settings*`) — "Módulos" accordion section with toggle list → families PATCH.
- Modify: onboarding flow (locate family-creation step, `backend/app/services/onboarding_service.py` + register/onboarding frontend) — starter choice: "Tareas y domingo" (side modules off: meals/shopping/calendar/pet off; budget/gigs/chat on) · "Familia completa" (NULL = all) · "Personalizado" (checklist). New column already supports it — starter just PATCHes after family creation.
- Test: extend `test_module_registry.py` for starter payloads; astro build.

- [ ] Implement; green; commit

### Task 12: Full verify + PR

- [ ] `cd backend && ruff check app`
- [ ] Full pytest (podman `family_app_backend` if up; else bare-metal per memory `project_local_tests_sin_podman`)
- [ ] `cd frontend && npm run check && npm run build`
- [ ] Update `CLAUDE.md` (economy modes now 4, grading, module registry — short deltas)
- [ ] Push branch, `gh pr create` to main with phase-sectioned body, DO NOT merge
