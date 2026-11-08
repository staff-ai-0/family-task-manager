# Early Bird Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Per-family 11:00 chore deadline for teens with two reminders, same-day "up for grabs" take-over, and three early-bird bonus tiers (per-chore points, +5 % weekly paycheck, $500 MXN every 3rd consecutive early week).

**Architecture:** Pure rules in `early_bird_rules.py` (no DB), DB queries / take / award / sweep in `early_bird_service.py` (ping_service style). One new assignment status `taken`, one settle table `early_bird_weeks`, a `*/5` leader cron. Paycheck +5 % computed in ONE helper used by projection and release. Frontend: one proxy route, copy-only `lib/earlyBird.ts`, two kid cards, one parent settings section, one template checkbox.

**Tech Stack:** FastAPI + SQLAlchemy async + Alembic (PG 15), APScheduler, Astro 5 SSR + vanilla script islands, vitest.

**Spec:** `docs/superpowers/specs/2026-11-07-early-bird-deadline-design.md` — read it first; this plan does not repeat its rules.

**Test runner (local):** `PT=/private/tmp/claude-501/-Users-jc-dev-2026-AgentIA-family-task-manager/eb7d42f8-1eee-456a-b44e-76ab8a5fbdd4/scratchpad/pt` — wraps `pytest -q --no-cov` with the local test DB (port 5435) + env, runs from `backend/`. Run ONLY the task's test files plus the listed neighbors; never the full suite inside a task (12 min). Frontend: `cd frontend && npx vitest run <file>` and `npx astro check`.

## Global Constraints

- Every query filters `family_id`; cross-family ids → 404.
- Money is integer centavos; points integer; rounding half-up via `(x*pct + 50)//100`.
- Times are family-local (`families.timezone` through `bank_service._safe_zoneinfo`). Deadline default `11:00`; R1 = D − 60 min, R2 = D − 30 min; early cutoff = R1 (strict `<`).
- Defaults: `early_bird_enabled=false`, `early_bird_bonus_pct=20` (0–100), `early_bird_week_pct=5` (0–50), `early_bird_streak_cents=50000` (0–1 000 000), streak length constant `3`, deadline 07:00–22:00 with minute % 5 == 0.
- Covered owners = role `TEEN` only; takers = `CHILD` or `TEEN`.
- New alembic revision id `early_bird`, `down_revision = "payout_receipts"`; single head; downgrade must round-trip.
- `cash_transactions.type` PG enum is NAME-valued → new member added as `'BONUS'`; `assignmentstatus` is VALUE-valued → add `'taken'`.
- No LLM calls. No native `alert/confirm/prompt`. Section-colored headers (`tone`), `buttonClass`, `text-brand-*-text`, no emoji in `<h1>`; visual + contrast vitest guards must stay green.
- New `family_id` table joins the family-export registry.
- User-facing copy ES/EN; kid copy ONLY in `frontend/src/lib/earlyBird.ts`; parent page may carry inline ES/EN ternaries (existing pattern).
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Non-UTC family timezone** — a teen in `America/Mexico_City` completing at 09:59 local gets the early bonus, at 10:00 local does not; the sweep sends R1 at 10:00 local, not 10:00 UTC. → Task 3 + Task 6 tests use `America/Mexico_City`.
2. **Re-shuffle after a take** — the weekly shuffle deletes PENDING rows; it must not delete the taker's PENDING row (`taken_from_id IS NOT NULL`), or the chore silently disappears from everyone. → Task 4 test `test_reshuffle_keeps_taken_rows`.
3. **Stale owner card** — owner taps "done" on a chore already taken → 422, no points. → Task 4 `test_owner_cannot_complete_after_take`.
4. **Parent retro "mark done" on a taken row** — must refuse (status not open). → Task 4 `test_mark_done_for_kid_rejects_taken`.
5. **Toggle off → on** — `early_bird_enabled_at` re-stamped; the re-enabling week is ineligible for weekly tiers and the previous run does not continue across the gap. → Task 1 `test_enabled_at_restamped_on_reenable` + Task 7 `test_gap_week_breaks_run`.

---

### Task 1: Data model, migration, schemas, export registry

**Files:**
- Create: `backend/migrations/versions/2026_11_07_early_bird.py`, `backend/app/models/early_bird_week.py`
- Modify: `backend/app/models/{family.py,task_template.py,task_assignment.py,cash_transaction.py,__init__.py}`, `backend/app/schemas/family.py`, `backend/app/schemas/task_template.py`, `backend/app/services/family_service.py:130-160`, `backend/app/services/family_export_service.py` (registry list near `PayoutReceipt` + dump path `progress/early_bird_weeks.json`)
- Test: `backend/tests/test_early_bird_model.py`, `backend/tests/test_migration_early_bird.py`

**Interfaces:**
- Produces:
  - `AssignmentStatus.TAKEN = "taken"`; `CashTransactionType.BONUS = "bonus"`.
  - `Family.early_bird_enabled: bool`, `.early_bird_enabled_at: datetime|None`, `.early_bird_deadline: datetime.time`, `.early_bird_days: list[int]|None`, `.early_bird_bonus_pct: int`, `.early_bird_week_pct: int`, `.early_bird_streak_cents: int`.
  - `TaskTemplate.early_bird_exempt: bool`.
  - `TaskAssignment.taken_by: UUID|None` (FK users SET NULL), `.taken_at: datetime|None`, `.taken_from_id: UUID|None` (FK task_assignments SET NULL, indexed), `.early_bonus_points: int|None`.
  - `EarlyBirdWeek` (`early_bird_weeks`): `id, family_id, user_id, week_of: date, result: str, run_weeks: int, bonus_cents: int=0, paid_at: datetime|None, created_at`; `UniqueConstraint("user_id","week_of", name="uq_early_bird_weeks_user_week")`; `CheckConstraint("result IN ('early','missed','neutral')", name="ck_early_bird_weeks_result")`.
  - `FamilyUpdate` + `FamilyResponse` gain the 7 family fields (`early_bird_deadline` serialized/accepted as `"HH:MM"` string; `early_bird_days` list of distinct ints 0–6, empty list rejected, `None` = every day). `TaskTemplateCreate/Update/Response` gain `early_bird_exempt` (create default `False`, update `Optional`).
  - `FamilyService.update_family` stamps `early_bird_enabled_at = now(UTC)` whenever the update sets `early_bird_enabled=True` while the stored value was `False`.

- [ ] **Step 1: Write failing tests** — `test_early_bird_model.py`:
  - `test_family_defaults`: new Family → enabled False, deadline `time(11,0)`, bonus 20, week 5, streak 50000, days None.
  - `test_assignment_taken_status_roundtrip`: insert assignment with `status=AssignmentStatus.TAKEN`, re-read → `TAKEN`.
  - `test_cash_bonus_type_roundtrip`: insert `CashTransaction(type=CashTransactionType.BONUS, ...)`, re-read.
  - `test_early_bird_week_unique`: two rows same (user, week) → `IntegrityError`.
  - `test_enabled_at_restamped_on_reenable`: PATCH on → stamped t1; off; on → t2 > t1.
  - `test_family_update_validation`: `early_bird_deadline="06:55"` → 422; `"11:03"` → 422; `"11:00"` ok; `early_bird_days=[7]` → 422; `[]` → 422; `early_bird_week_pct=51` → 422.
  - `test_export_includes_early_bird_weeks`: family export bundle contains `progress/early_bird_weeks.json` with the row.
  - `test_migration_early_bird.py::test_round_trip`: follow `tests/test_migration_weekly_quests.py`'s pattern — upgrade head → downgrade `-1` (a `taken` row becomes `cancelled`, a `BONUS` cash row becomes `ADJUSTMENT`, table/columns gone) → upgrade head.
- [ ] **Step 2: Run** `$PT tests/test_early_bird_model.py tests/test_migration_early_bird.py` → FAIL (attributes missing).
- [ ] **Step 3: Implement** models, migration, schemas, stamping, registry. Migration: `op.execute("ALTER TYPE assignmentstatus ADD VALUE IF NOT EXISTS 'taken'")` and `… cashtransactiontype ADD VALUE IF NOT EXISTS 'BONUS'` inside `with op.get_context().autocommit_block():`. Downgrade: update rows to `cancelled` / `ADJUSTMENT`, then recreate each enum without the value (rename old type → create new → `ALTER COLUMN … TYPE … USING col::text::newtype` → drop old; re-apply column defaults). `early_bird_deadline` = `sa.Time()` server_default `'11:00'`.
- [ ] **Step 4: Run** same command + `tests/test_family_delete_export.py tests/test_quest_model.py` → PASS.
- [ ] **Step 5: Commit** `feat(early-bird): data model, migration, settings schemas`.

### Task 2: Pure rules

**Files:**
- Create: `backend/app/services/early_bird_rules.py`
- Test: `backend/tests/test_early_bird_rules.py`

**Interfaces:**
- Consumes: Task 1 enums.
- Produces (all pure, no DB):
  - Constants `STREAK_WEEKS = 3`, `R1_BEFORE = timedelta(minutes=60)`, `R2_BEFORE = timedelta(minutes=30)`, `GRABS_PUSH_WINDOW = timedelta(minutes=60)`, `SETTLE_LOOKBACK_WEEKS = 3`, `PENDING_GRACE_DAYS = 7`.
  - `@dataclass(frozen=True) EarlyBirdConfig(enabled: bool, enabled_at: datetime|None, deadline: time, days: frozenset[int]|None, bonus_pct: int, week_pct: int, streak_cents: int, tz: ZoneInfo)` + `classmethod from_family(fam) -> EarlyBirdConfig` (accepts ORM row or `Row` with those attribute names + `timezone`).
  - `@dataclass(frozen=True) DayTimes(r1: datetime, r2: datetime, deadline: datetime)`; `day_times(cfg, day: date) -> DayTimes` (tz-aware, `cfg.tz`).
  - `is_active_day(cfg, day: date) -> bool` — enabled, `enabled_at` set, weekday in `days` (None = all), `day_times(day).r1 > enabled_at`.
  - `week_eligible(cfg, monday: date) -> bool` — enabled, `enabled_at < day_times(monday).r1`.
  - `@dataclass(frozen=True) CoveredRow(assignment_id: UUID, assigned_date: date, status: AssignmentStatus, approval: ApprovalStatus, grade: str|None, completed_at: datetime|None)`.
  - `chore_state(row, cfg, now: datetime, *, grace: bool = False) -> Literal["early","pending","open","missed"]` — early: completed, `completed_at < r1`, approval NONE/APPROVED, grade not `missed`/`partial`; pending: completed before r1 with approval PENDING (→ `early` when `grace`); open: status PENDING/OVERDUE/CLAIMED and `now < r1`; everything else (late, rejected, partial, taken, open past r1, legacy `completed_at=None`) → `missed`.
  - `day_result(states: list[str]) -> Literal["early","missed","pending","open","neutral"]` — empty → neutral; any missed → missed; any open → open; any pending → pending; else early.
  - `week_result(day_results: list[str], *, eligible: bool, week_over: bool) -> Literal["ineligible","early","missed","neutral","pending","in_progress"]` — order: not eligible → ineligible; any missed → missed; not week_over → in_progress; any pending/open → pending; any early → early; else neutral.
  - `next_run(prev_run: int, result: str) -> int` — early → prev+1, missed → 0, neutral → prev.
  - `pays_streak(result: str, run: int) -> bool` — `result == "early" and run > 0 and run % STREAK_WEEKS == 0`.
  - `early_bonus_points(effective_points: int, pct: int) -> int` — 0 when either ≤ 0, else `max(1, (effective_points*pct + 50)//100)`.
  - `reminder_stage(now: datetime, t: DayTimes) -> Literal["r1","r2","grabs"]|None` — `[r1,r2)`, `[r2,deadline)`, `[deadline, deadline+GRABS_PUSH_WINDOW)`.
  - `week_bonus(base_cents: int, pct: int, result: str) -> int` — `base*pct//100` iff result early and both > 0, else 0.

- [ ] **Step 1: Write failing tests** (pure, no fixtures) — one test per function above, including: `day_times` for `America/Mexico_City` at deadline 11:00 → r1 10:00 local; `is_active_day` false when `days={0..4}` on a Saturday and false for a day whose r1 ≤ enabled_at; `chore_state` boundary 09:59:59 → early, 10:00:00 → missed; partial → missed; pending + grace → early; `week_result(["early","missed"], eligible=True, week_over=False) == "missed"`; `["early","pending"], week_over=True → "pending"`; `next_run(2,"neutral") == 2`; `pays_streak("early",3)` and `(…,6)` True, `(…,4)` False; `early_bonus_points(10,20) == 2`, `(3,20) == 1`, `(10,0) == 0`; `reminder_stage` at r2−1s → r1, at deadline+60min → None; `week_bonus(80000,5,"early") == 4000`, `(…,"pending") == 0`.
- [ ] **Step 2: Run** `$PT tests/test_early_bird_rules.py` → FAIL (ImportError).
- [ ] **Step 3: Implement** `early_bird_rules.py`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(early-bird): pure deadline/early/week rules`.

### Task 3: Covered rows + early bonus award

**Files:**
- Create: `backend/app/services/early_bird_service.py`
- Modify: `backend/app/services/task_assignment_service.py` (mandatory non-proof branch of `complete_assignment` ~L1789; mandatory branch of `approve_gig` approve path ~L2412), `backend/app/services/points_service.py`, `backend/app/models/point_transaction.py`
- Test: `backend/tests/test_early_bird_bonus.py`

**Interfaces:**
- Consumes: Task 1 columns, Task 2 rules.
- Produces:
  - `PointTransaction.create_bonus(user_id, family_id, points, balance_before, description, assignment_id=None)` (type `BONUS`) and `PointsService.award_bonus_points(db, user_id, family_id, points, description, assignment_id=None) -> PointTransaction` (no commit, row-locks user like `award_gig_points`).
  - `class EarlyBirdService` with
    - `async config(db, family_id) -> EarlyBirdConfig`
    - `async covered_rows(db, cfg, family_id, user_id, start: date, end: date) -> list[CoveredRow]` — inclusive dates; joins template (`is_bonus=false`, `early_bird_exempt=false`) and user (`role=TEEN`); `taken_from_id IS NULL`; `status != cancelled`; filtered to `is_active_day`.
    - `async maybe_award_early_bonus(db, assignment, template, *, credit_pct: int = 100) -> int` — no commit; returns points awarded (0 when not eligible); eligible iff cfg enabled and `bonus_pct > 0`, owner is TEEN, template not bonus/exempt, `taken_from_id is None`, `is_active_day(assigned_date)`, `completed_at < r1`, `early_bonus_points is None`, `credit_pct == 100`. Sets `assignment.early_bonus_points`; description `"Madrugador +{n}"`.
  - Hook calls: non-proof mandatory completion (after `award_assignment_completion`) and `approve_gig` mandatory approve with `credit_pct=award_pct`.

- [ ] **Step 1: Write failing tests** — family tz `America/Mexico_City`, enabled with `enabled_at` a week ago, teen + 10-pt template; freeze completion time by patching `datetime` used for `completed_at`, or by setting `completed_at` before calling the proof/approve path (prefer calling `complete_assignment` with `app.services.task_assignment_service.datetime` patched):
  - `test_complete_before_cutoff_awards_bonus`: 09:59 local → `early_bonus_points == 2`, one BONUS transaction of 2, user points 12.
  - `test_complete_at_cutoff_no_bonus`: 10:00 local → 0, no BONUS row.
  - `test_child_owner_no_bonus`, `test_exempt_template_no_bonus`, `test_disabled_family_no_bonus`, `test_inactive_weekday_no_bonus`.
  - `test_proof_chore_bonus_on_full_approval`: proof chore completed 09:30, approved `full` → bonus; `test_proof_chore_partial_no_bonus`; `test_proof_chore_rejected_no_bonus`.
  - `test_bonus_idempotent`: calling `maybe_award_early_bonus` twice → one transaction.
  - `test_covered_rows_filters`: bonus/exempt/child-owned/taken-from/cancelled rows excluded; other family's rows excluded.
- [ ] **Step 2: Run** `$PT tests/test_early_bird_bonus.py` → FAIL.
- [ ] **Step 3: Implement** service methods + PointsService/PointTransaction helpers + two hook calls.
- [ ] **Step 4: Run** same + `tests/test_task_assignments*.py tests/test_graded_review*.py` (whatever exists matching `ls tests | grep -E "assignment|grade|proof"`) → PASS.
- [ ] **Step 5: Commit** `feat(early-bird): early bonus points on completion/approval`.

### Task 4: Up for grabs + take

**Files:**
- Modify: `backend/app/services/early_bird_service.py`, `backend/app/services/task_assignment_service.py` (shuffle PENDING delete ~L1117: add `TaskAssignment.taken_from_id.is_(None)`), `backend/app/services/bank_service.py` (`_chore_units`: taken → `lost_units += full`; `_chore_week_tasks`: bucket `"taken"`), `backend/app/services/notification_service.py` (`_COPY["chore_taken"]`), `backend/app/models/notification.py` (`NotificationType.CHORE_TAKEN = "chore_taken"`)
- Test: `backend/tests/test_early_bird_take.py`

**Interfaces:**
- Produces:
  - `@dataclass GrabRow(assignment_id: UUID, title: str, title_es: str|None, points: int, owner_id: UUID, owner_name: str)`
  - `async EarlyBirdService.grabbable(db, family_id, now: datetime|None = None) -> list[GrabRow]` — covered rows dated family-local today, status PENDING/OVERDUE, `now >= deadline`, cfg enabled + active day.
  - `async EarlyBirdService.can_take(db, taker: User, row_template) -> str|None` — reason key or None: `"not_kid"`, `"role_not_allowed"`, `"finish_yours_first"`.
  - `async EarlyBirdService.take(db, family_id, taker: User, assignment_id, now=None) -> TaskAssignment` — commits; errors: `NotFoundException` (missing / other family), `ConflictException("already_taken")` → 409 when status is TAKEN, `ValidationException` → 422 for `not_grabbable` (before deadline, not covered, not today, completed), `ForbiddenException` → 403 for `own_chore` and `can_take` reasons. Row-locks via `TaskAssignmentService.get_assignment(..., for_update=True)`. Creates taker row (`status=PENDING`, same `template_id/assigned_date/week_of`, `taken_from_id`), sets owner `status=TAKEN, taken_by, taken_at`, then `NotificationService.create_localized(key="chore_taken", user_id=owner, params={"taker": name, "title": title}, link="/dashboard")` best-effort after commit. (Use the project's existing exception classes in `app/core/exceptions.py`; add `ConflictException` only if absent.)
  - `_COPY["chore_taken"]`: ES `"🙋 {taker} tomó tu tarea"` / body `"'{title}' ya no es tuya — se acabó el tiempo."`; EN `"🙋 {taker} took your chore"` / `"'{title}' is no longer yours — time ran out."`.

- [ ] **Step 1: Write failing tests** (deadline passed: build `now` = today local 11:05 and pass it explicitly; teen owner + teen taker + child taker):
  - `test_grabbable_after_deadline_only`: at 10:59 → []; at 11:05 → [row].
  - `test_take_moves_chore`: owner row TAKEN/taken_by; taker row PENDING with `taken_from_id`; owner got `chore_taken` notification.
  - `test_second_take_409` (sequential second call raises conflict).
  - `test_take_own_chore_403`, `test_taker_with_open_chores_403` (`finish_yours_first`), `test_allowed_roles_blocks_child` (template `allowed_roles=["teen"]`), `test_parent_cannot_take_403`.
  - `test_other_family_404`, `test_exempt_not_grabbable_422`, `test_yesterday_not_grabbable_422`.
  - `test_owner_cannot_complete_after_take` (`complete_assignment` on owner row → `ValidationException`).
  - `test_mark_done_for_kid_rejects_taken`.
  - `test_reshuffle_keeps_taken_rows`: take, then `shuffle_tasks` for the week → taker's row still exists.
  - `test_taken_counts_as_miss`: owner `ProgressService.day_states` for today → missed; `BankService._chore_units` → taken points in assigned and lost, not done.
  - `test_taker_completes_earns_points`: taker completes → `effective_points` awarded to taker, no early bonus.
- [ ] **Step 2: Run** `$PT tests/test_early_bird_take.py` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** same + `tests/test_shuffle*.py tests/test_progress*.py tests/test_bank*.py tests/test_payout*.py` → PASS.
- [ ] **Step 5: Commit** `feat(early-bird): up-for-grabs take-over with taken status`.

### Task 5: Weekly +5 % on the chore paycheck

**Files:**
- Modify: `backend/app/services/early_bird_service.py`, `backend/app/services/bank_service.py` (`_paycheck_projection` ~L587, `chore_paycheck_preview`, `list_outstanding_weeks`, `release_chore_paycheck` ~L884), `backend/app/schemas/` file holding the paycheck preview / outstanding response models (find with `grep -rn "projected_cents" backend/app/schemas`)
- Test: `backend/tests/test_early_bird_paycheck.py`

**Interfaces:**
- Produces:
  - `async EarlyBirdService.week_status(db, cfg, family_id, user_id, monday: date, now: datetime) -> tuple[str, dict[date, str]]` — `(week_result, {day: day_result})` over Mon–Sun, `week_over = now.date() > monday+6d` (family-local), `grace = now.date() > monday+6d+PENDING_GRACE_DAYS`.
  - `async EarlyBirdService.week_bonus_cents(db, family_id, user_id, monday: date, base_cents: int, now=None) -> int` — uses `week_bonus`.
  - Bank: one private helper `BankService._early_bird_bonus(db, family_id, user_id, week_monday, base) -> int` called from both `_paycheck_projection` (adds to `amount_cents`, returns `early_bird_bonus_cents`) and `release_chore_paycheck` (adds before `adjustment_cents`; description suffix `" · +{pct}% madrugador"` when > 0). Preview / outstanding responses gain `early_bird_bonus_cents: int = 0`.

- [ ] **Step 1: Write failing tests** (teen `points_rate`, `point_value_cents=100`, last week: 4 covered chores of 10 pts all early ⇒ base 4000):
  - `test_projection_adds_week_bonus`: `chore_paycheck_preview(week_of=last_monday)` → `projected_cents == 4200`, `early_bird_bonus_cents == 200`.
  - `test_release_pays_bonus`: release → ALLOWANCE total 4200.
  - `test_receipt_confirm_consistent`: confirm a receipt of 4200 through `payout_receipt_service` → adjustment 0 (no extra row).
  - `test_missed_day_no_bonus`, `test_current_week_no_bonus`, `test_pending_review_no_bonus_until_grace`, `test_flat_mode_untouched`, `test_week_pct_zero_off`, `test_ineligible_enable_week_no_bonus`.
- [ ] **Step 2: Run** `$PT tests/test_early_bird_paycheck.py` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** same + `tests/test_bank*.py tests/test_payout*.py tests/test_chore_paycheck*.py` → PASS.
- [ ] **Step 5: Commit** `feat(early-bird): +5% chore paycheck for an early week`.

### Task 6: Reminder sweep (R1, R2, up-for-grabs pushes) + cron

**Files:**
- Modify: `backend/app/services/early_bird_service.py`, `backend/app/models/notification.py` (`DEADLINE_SOON = "deadline_soon"`, `UP_FOR_GRABS = "up_for_grabs"`), `backend/app/services/notification_service.py` (`SUPERSEDING_TYPES` += both; `_COPY` keys below), `backend/app/main.py` (`_register_cron_jobs`: `_early_bird_sweep`, `minute="*/5"`, `id="early_bird_sweep"`)
- Test: `backend/tests/test_early_bird_sweep.py`

**Interfaces:**
- Produces: `async EarlyBirdService.run_sweep(db, now: datetime|None = None) -> dict[str, int]` with keys `reminders, grabs, settled, paid` (settled/paid filled by Task 7; 0 here). Per family (enabled, not deleted; try/except + rollback per family and per kid, ping_service pattern): stage = `reminder_stage(local_now, day_times(today))` when `is_active_day(today)`.
  - `r1`/`r2`: each TEEN (participating) with ≥ 1 covered chore today in PENDING/OVERDUE and no `deadline_soon` row since that stage's start → `create_localized(key, params={"n": n, "deadline": "HH:MM"}, expires_at=deadline, link="/dashboard", push_tag="ftm-early-bird")`; keys `deadline_r1`/`deadline_r1_one`/`deadline_r2`/`deadline_r2_one`.
  - `grabs`: owners of open covered chores → `grabs_owner` (`n`); every other participating CHILD/TEEN who passes role/allowed_roles for ≥ 1 grabbable row → `grabs_open` / `grabs_open_one` (`n`); send record = no `up_for_grabs` row since deadline; `expires_at` = next local midnight.
  - Copy (ES / EN), type in parentheses:
    - `deadline_r1` (deadline_soon): "⏰ Falta 1 hora" / "⏰ 1 hour left" — body "Termina tus {n} tareas antes de las {deadline} y gana tu bono madrugador." / "Finish your {n} chores before {deadline} for your early-bird bonus." (`_one`: "tu tarea"/"your chore").
    - `deadline_r2` (deadline_soon): "⚠️ Faltan 30 minutos" / "⚠️ 30 minutes left" — "A las {deadline} tus {n} tareas quedan libres para tus hermanos." / "At {deadline} your {n} chores are up for grabs." (`_one` singular).
    - `grabs_owner` (up_for_grabs): "⏰ Se acabó el tiempo" / "⏰ Time's up" — "{n} de tus tareas quedaron libres. Hazlas antes de que alguien las tome." / "{n} of your chores are up for grabs. Do them before someone takes them."
    - `grabs_open` (up_for_grabs): "🙌 {n} tareas libres" / "🙌 {n} chores up for grabs" — "Tómalas y gana sus puntos." / "Take them and earn their points." (`_one` singular).

- [ ] **Step 1: Write failing tests** (family tz `America/Mexico_City`, deadline 11:00, inject `now` as UTC equivalents of local times):
  - `test_r1_sent_at_1000_local` (10:00 local → one `deadline_soon` row, `expires_at` = 11:00 local); `test_nothing_at_1000_utc_when_local_0400`.
  - `test_r1_not_resent_same_window` (two runs 10:00 and 10:05 → 1 row).
  - `test_r2_sent_at_1030` (after R1 → 2 rows total; R1 row marked read by superseding).
  - `test_late_start_sends_r2_only` (first run 10:40 → exactly 1 row, key r2 copy).
  - `test_no_reminder_when_done` (all covered done → 0 rows).
  - `test_child_and_exempt_ignored`.
  - `test_grabs_pushes_at_1100` (owner gets `grabs_owner`, sibling gets `grabs_open`; second run at 11:05 → no new rows; run at 12:05 → none).
  - `test_disabled_or_inactive_day_noop`.
  - `test_one_family_failure_isolated` (patch config of first family to raise → second family still gets its row).
  - `test_cron_registered`: `_register_cron_jobs` on a fresh `AsyncIOScheduler` contains job id `early_bird_sweep`.
- [ ] **Step 2: Run** `$PT tests/test_early_bird_sweep.py` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** same + `tests/test_ping_sweep.py tests/test_notification*.py` → PASS.
- [ ] **Step 5: Commit** `feat(early-bird): 10:00/10:30 reminders and up-for-grabs pushes`.

### Task 7: Week settlement + $500 every 3rd early week

**Files:**
- Modify: `backend/app/services/early_bird_service.py` (`run_sweep` calls settlement once per family per run, after reminders), `backend/app/models/notification.py` (`EARLY_BIRD_PAYOUT = "early_bird_payout"`), `backend/app/services/notification_service.py` (`_COPY` keys)
- Test: `backend/tests/test_early_bird_settle.py`

**Interfaces:**
- Consumes: Task 5 `EarlyBirdService.week_status` (the ONLY place a week's result is computed — the 5 % and the settlement must agree).
- Produces: `async EarlyBirdService.settle_teen(db, cfg, family_id, user_id, now) -> int` (number of payouts, 0/1+). Walks Mondays from `this_monday − SETTLE_LOOKBACK_WEEKS weeks` to last Monday, oldest first; skips weeks with a row; stops at the first `pending`/`in_progress`; skips (no row) `ineligible`; inserts `EarlyBirdWeek(result, run_weeks=next_run(prev.run_weeks if prev row for monday−7d exists else 0, result))`; if `pays_streak` and `cfg.streak_cents > 0`: guarded `UPDATE early_bird_weeks SET paid_at=now, bonus_cents=:c WHERE id=:id AND paid_at IS NULL`, and only when rowcount == 1 credit `CashService.credit_split_rows(..., CashTransactionType.BONUS, entitled=await CashService._bank_automation_entitled(db, family_id), description=f"Bono madrugador {STREAK_WEEKS} semanas")` (row-lock user + account with the cash_service helpers), commit, then notify teen `early_bird_payout_kid` and parents broadcast `early_bird_payout_parent` (best-effort).
  - Copy: `early_bird_payout_kid`: "🏆 ¡{weeks} semanas madrugador!" / "🏆 {weeks} early-bird weeks!" — "Ganaste {amount}." / "You earned {amount}."; `early_bird_payout_parent` (user_id None): "🏆 {kid}: {weeks} semanas madrugador" / "🏆 {kid}: {weeks} early-bird weeks" — "Se acreditaron {amount} a su saldo." / "{amount} was credited to their balance." (`amount` via `bank_service._fmt_mxn`).

- [ ] **Step 1: Write failing tests** (enabled 5 weeks ago; helper builds a week of covered chores early / missed / none):
  - `test_three_early_weeks_pay_500`: weeks −3,−2,−1 early → rows run 1,2,3; one BONUS cash credit 50000 total; kid + parent notifications.
  - `test_second_run_no_double_pay` (run sweep twice → still one credit).
  - `test_missed_resets_run`: early, missed, early → runs 1,0,1, no pay.
  - `test_neutral_keeps_run`: early, neutral, early, early → runs 1,1,2,3 → pays on the 4th week.
  - `test_pending_blocks_then_grace`: week with a proof chore pending review → no row; advance `now` beyond 7 days after week end → settles early.
  - `test_gap_week_breaks_run`: disable → enable (restamp) → weeks before the restamp week are skipped as ineligible and the run restarts at 1.
  - `test_streak_cents_zero_no_pay`, `test_week_six_pays_again`.
- [ ] **Step 2: Run** `$PT tests/test_early_bird_settle.py` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** same + `tests/test_early_bird_sweep.py tests/test_cash*.py` → PASS.
- [ ] **Step 5: Commit** `feat(early-bird): weekly settlement and 3-week cash bonus`.

### Task 8: API

**Files:**
- Create: `backend/app/api/routes/early_bird.py`, `backend/app/schemas/early_bird.py`
- Modify: router registration (where `progress` router is included — `grep -n "progress" backend/app/main.py backend/app/api/*.py`)
- Test: `backend/tests/test_early_bird_api.py`

**Interfaces:**
- Produces (prefix `/api/early-bird`):
  - `GET /me` (CHILD/TEEN; parent → 403) → `EarlyBirdMe`: `enabled: bool`, `applies: bool` (caller is TEEN and enabled), `deadline: "HH:MM"`, `cutoff_at: datetime|None`, `deadline_at: datetime|None` (today, None when not an active day), `today: Literal["early","pending","open","missed","neutral"]|None`, `week: list[{date, state}]` (Mon–Sun, future days `"future"`), `week_result: str`, `run_weeks: int` (last settled row's run, 0 none), `streak_weeks: 3`, `streak_cents`, `week_pct`, `bonus_pct`, `grabs: list[{assignment_id, title, points, owner_name}]`, `take_block: str|None` (can_take reason for the caller).
  - `POST /grabs/{assignment_id}/take` (CHILD/TEEN) → `TaskAssignmentResponse` of the new row; maps service errors to 404/409/422/403 with `detail` = reason key.
  - `GET /family` (PARENT) → `list[{user_id, name, today, week, week_result, run_weeks}]` for the family's TEENs.
  - Title chosen by caller `preferred_lang` (`title_es` fallback to `title`).
- [ ] **Step 1: Write failing tests** via `client` + auth fixtures: `test_me_teen_shape`, `test_me_parent_403`, `test_me_disabled_family` (`enabled=False`, empty week, no grabs), `test_take_endpoint_happy`, `test_take_endpoint_409_race`, `test_take_cross_family_404`, `test_family_overview_parent_only`.
- [ ] **Step 2: Run** `$PT tests/test_early_bird_api.py` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** same + `tests/test_ai_gating.py` (must remain green — no LLM site added) → PASS. Then `cd backend && ruff check app` → clean.
- [ ] **Step 5: Commit** `feat(early-bird): /api/early-bird endpoints`.

### Task 9: Kid/teen frontend

**Files:**
- Create: `frontend/src/pages/api/early-bird/[...path].ts` (`createApiProxy({ name: "early-bird" })`), `frontend/src/lib/earlyBird.ts`, `frontend/src/components/home/EarlyBirdCard.astro`, `frontend/src/components/home/UpForGrabs.astro`, `frontend/test/earlyBird.test.ts`
- Modify: `frontend/src/pages/dashboard.astro` (fetch `/api/early-bird/me` next to `/api/progress/quest`, tolerate failure → null), `frontend/src/components/home/KidHome.astro` (props `earlyBird`, render card above `QuestCard` when `applies`, `UpForGrabs` when `grabs.length`), every place that renders an assignment status label (`grep -rn "\"overdue\"\|'overdue'" frontend/src` → add `taken`: ES "Tomada" / EN "Taken"), teen paycheck meter component (`grep -rln "projected_cents" frontend/src`) → line "incl. +{pct}% madrugador" when `early_bird_bonus_cents > 0`.

**Interfaces:**
- Consumes: Task 8 `EarlyBirdMe`.
- Produces in `lib/earlyBird.ts`: `earlyBirdCopy(lang)` (all kid strings), `earlyBirdView(me, lang, now: Date) -> EarlyBirdView|null` (null when `!me?.applies && !me?.grabs?.length`), `countdownLabel(target: Date, now: Date, lang) -> string` ("45 min", "1 h 05 min"), `takeErrorMessage(detail: string, lang) -> string` for `already_taken`, `finish_yours_first`, `role_not_allowed`, `own_chore`, `not_grabbable`.
- UpForGrabs "Tomar/Take" button: `fetch("/api/early-bird/grabs/<id>/take", {method:"POST"})` → on 2xx `queueToast` + reload; on error `showToast(takeErrorMessage(detail))`. Synchronous button disable while in flight.
- [ ] **Step 1: Write failing vitest** `earlyBird.test.ts`: `countdownLabel` cases; `earlyBirdView` → state `"on_track"` before cutoff with open chores, `"late"` after cutoff, run text "1/3", null when not applies and no grabs; `takeErrorMessage("already_taken","es")` non-empty and distinct from `"own_chore"`.
- [ ] **Step 2: Run** `cd frontend && npx vitest run test/earlyBird.test.ts` → FAIL.
- [ ] **Step 3: Implement** lib + components + wiring (header tone: card lives inside the home, use the sun/earning palette for the card; `buttonClass("primary","sm")` for Take).
- [ ] **Step 4: Run** `npx vitest run` (all frontend tests incl. visual-consistency, contrast, no-native-dialogs) and `npx astro check` → PASS / 0 errors.
- [ ] **Step 5: Commit** `feat(early-bird): teen card and up-for-grabs on the kid home`.

### Task 10: Parent settings, template checkbox, docs

**Files:**
- Modify: `frontend/src/pages/parent/settings/family.astro` (new section after quest section: toggle, `type="time"` deadline step 300, Mon–Sun chips, three number inputs — bonus % 0–100, week % 0–50, streak in pesos 0–10000 converted ×100 — each saved with `PATCH` like the quest section; a per-teen status list from `GET /api/early-bird/family`), `frontend/src/components/TaskCreateModal.astro` (+ the template edit page under `frontend/src/pages/parent/tasks/[id]`) checkbox "Tarea de la tarde — sin hora límite" / "Evening chore — no deadline" bound to `early_bird_exempt`, hidden when `is_bonus`; parent payouts page shows "incl. +5 % madrugador" when `early_bird_bonus_cents > 0`; `docs/USER_GUIDE_EN.md`, `docs/USER_GUIDE_ES.md` (new "Early bird / Madrugador" section: deadline, reminders, up for grabs, the three tiers, evening-chore exemption); `CLAUDE.md` (Additional domains row **Early bird** with: routes, `taken` status rationale, tier rules, cron `*/5`, settle table, single 5 % helper).
- Test: `frontend/test/visual-consistency.test.ts` etc. (existing guards), `npx astro check`.

- [ ] **Step 1:** Implement settings section + checkbox + payouts line.
- [ ] **Step 2: Run** `cd frontend && npx vitest run && npx astro check && npx astro build` → all green.
- [ ] **Step 3:** Write docs sections + CLAUDE.md row.
- [ ] **Step 4: Commit** `feat(early-bird): parent settings, evening-chore flag, docs`.

### Task 11: Whole-branch verification

- [ ] **Step 1:** `cd backend && ruff check app` → clean.
- [ ] **Step 2:** Full backend suite once: `$PT tests/ -x -q` (run in background; ~12 min) → all pass.
- [ ] **Step 3:** Alembic round trip against the test DB: `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` with `DATABASE_URL` pointed at a scratch database → no errors.
- [ ] **Step 4:** Whole-branch review (fresh reviewer on the diff vs `origin/main`), fix findings, re-run affected tests.
