# Chore rules v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-family chore cutoff with a 20:30–22:30 up-for-grabs window, a weekly pay ladder (floor at 60 %, early bonus 5/10/15 % only at 100 %), and two teen alarms a day.

**Architecture:** Extend Early Bird in place. Pure rules in `early_bird_rules.py` gain a cutoff and a ladder function; `EarlyBirdService.week_metrics` is the single place the weekly percentages are computed; `BankService` is the single place pay is computed from them. Config lives in new `families` columns.

**Tech Stack:** FastAPI, SQLAlchemy 2 async, Alembic, pytest (test DB :5435), Astro 5 vanilla scripts, vitest.

**Spec:** `docs/superpowers/specs/2026-11-12-chore-rules-v2-design.md`

## Global Constraints

- Percentages are over the Mon–Sun week, family timezone, covered chores only (mandatory; bonus tasks and `early_bird_exempt` templates excluded) — the existing `EarlyBirdService.covered_rows` set.
- Defaults: cutoff `20:30`, grab window end `22:30`, teen alarms `15:00` / `19:00`, early deadline stays `11:00`, streak prize new-family default `38000` cents.
- Ladder: completed < 60 % → base pay 0; 60–99 % → per-task pay (existing `_chore_units` math); 100 % → all pay + bonus on base: early share ≥80 % → 5, ≥90 % → 10, 100 % → 15, otherwise 0. **Bonus requires 100 % completion.** `flat` allowance mode excluded.
- A chore completed after its cutoff counts as not completed. Graded `missed` / `partial` count as not completed **for the percentage** (partial still pays its scaled points under per-task pay).
- Money math is integer; no float cents (`//` with the existing rounding helpers).
- Every new family-scoped query filters by `family_id`. Never `sudo podman`. No native `alert/confirm/prompt` (vitest guard). Copy only in `lib/earlyBird.ts` (kid) and `lib/earlyBirdSettings.ts` (parent), ES + EN.
- `early_bird_week_pct` is retired: column stays, nothing reads it. Per-chore `early_bird_bonus_pct` and the streak mechanism are untouched.
- Do not bulk-update existing families' `early_bird_streak_cents`.
- Backend tests: `podman exec -e PYTHONPATH=/app family_app_backend pytest <path> -v` (or the bare-metal venv recipe in CLAUDE.md). Never run the full suite inside an agent; run the targeted files.

## Review Focus

- Week with zero covered chores: ladder must be neutral (no floor, no bonus), never divide by zero.
- A kid exactly at 60 % / 80 % / 90 % / 100 % (boundaries are inclusive).
- 100 % completed but a chore was completed 1 s after the cutoff → not 100 %.
- Parent `mark-done-for-kid` after the cutoff still counts (explicit parent action).
- Family that switched Early Bird off: no floor, no bonus, no grabs, no alarms.
- Existing early-bird week streak/settle behavior unchanged (`test_early_bird_settle.py`, `test_early_bird_sweep.py` stay green).
- **Open question for the parents (flag at handoff, do not resolve silently):** existing code treats "early" as completed before **R1 = deadline − 60 min (10:00)**; the new ladder says "before 11:00". Ladder uses the 11:00 `deadline`; per-chore +20 % and the streak week keep R1.

---

### Task 1: Config columns, migration, schemas

**Files:**
- Modify: `backend/app/models/family.py` (next to `early_bird_*`, ~line 56–67)
- Create: `backend/migrations/versions/2026_11_12_chore_rules_v2.py`
- Modify: `backend/app/schemas/family.py`, `backend/app/services/family_service.py` (wherever `early_bird_deadline` is read/written — grep it)
- Test: `backend/tests/test_chore_rules_config.py`, extend `backend/tests/test_migration_early_bird.py` pattern for a round-trip

**Interfaces:**
- Produces: `Family.chore_cutoff: time` (default 20:30), `Family.grab_window_end: time` (22:30), `Family.teen_alarm_1: time` (15:00), `Family.teen_alarm_2: time` (19:00), `Family.rules_version: int` (default 1). All `nullable=False` with `server_default`. Schema fields with validation: cutoff 17:00–23:00 and after `early_bird_deadline`; `grab_window_end` > cutoff and ≤ 23:30; alarms 06:00–cutoff, 5-minute steps, alarm_1 < alarm_2.

- [ ] **Step 1: Write failing tests** — `test_chore_rules_config.py::test_defaults`, `::test_update_bumps_rules_version` (PUT family settings changing `chore_cutoff` → `rules_version` 1→2; unchanged PUT keeps 1; changing `early_bird_deadline` or `early_bird_streak_cents` also bumps), `::test_validation_rejects_cutoff_before_deadline`, `::test_alarm_order`.
- [ ] **Step 2: Run** `pytest tests/test_chore_rules_config.py -v` → FAIL (no columns).
- [ ] **Step 3: Add columns + Alembic revision** (single head; `down_revision` = `2026_11_12_early_bird_past_periods`), server defaults as strings (`"20:30"`). New-family streak default: change the model default only (`default=38000`, **not** `server_default`, so existing rows are not rewritten) — verify with a test that an existing row keeps 50000.
- [ ] **Step 4: Implement validation + `rules_version` bump** in `family_service` update path: compare old vs new of the watched fields, bump in the same transaction.
- [ ] **Step 5: Run** the new tests + `tests/test_migration_early_bird.py -v` + the alembic upgrade/downgrade/upgrade round-trip → PASS.
- [ ] **Step 6: Commit** `feat(early-bird): chore-rules config columns + rules_version`

### Task 2: Pure rules — cutoff and ladder

**Files:**
- Modify: `backend/app/services/early_bird_rules.py`
- Test: `backend/tests/test_chore_ladder.py`

**Interfaces:**
- Consumes: `EarlyBirdConfig`, `CoveredRow`, `DayTimes` (existing).
- Produces:
  - `EarlyBirdConfig` gains `cutoff: time`, `grab_end: time` (filled in `from_family`).
  - `DayTimes` gains `cutoff: datetime`, `grab_end: datetime`.
  - `def completed_in_time(row: CoveredRow, cfg, *, grace: bool = False) -> bool` — COMPLETED, `completed_at < cutoff` of `assigned_date`, grade not in (`missed`,`partial`), approval NONE/APPROVED (or PENDING with `grace`). A row whose `mark_done_for_kid` flag/note path set `completed_at` after cutoff — see Step 3.
  - `def done_early(row, cfg, *, grace=False) -> bool` — `completed_in_time` and `completed_at < deadline` (11:00, **not** R1).
  - `@dataclass(frozen=True) class LadderResult: tier: Literal["neutral","no_pay","per_task","bonus"]; bonus_pct: int; completed: int; early: int; total: int`
  - `def week_ladder(completed: int, early: int, total: int) -> LadderResult`.

- [ ] **Step 1: Write failing tests** `test_chore_ladder.py`: parametrized `week_ladder` — `(0,0,0)→neutral`; `(5,0,10)→no_pay`; `(6,0,10)→per_task` (60 % inclusive); `(59,59,60)` → per_task, bonus 0; `(10,8,10)→bonus 5`; `(10,9,10)→bonus 10`; `(10,10,10)→bonus 15`; `(10,7,10)→bonus tier with pct 0` (100 % done, 70 % early → tier `bonus`, `bonus_pct == 0`); `(9,9,10)→per_task`, bonus 0. Plus `completed_in_time` at cutoff−1 s true / cutoff false; `done_early` at 10:59 true / 11:00 false.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Percent comparisons via integer cross-multiplication (`completed * 100 >= 60 * total`), never float. Retroactive `mark-done-for-kid` rows have a `completed_at` after the cutoff but must still count as completed (explicit parent action). Read `mark_done_for_kid` in `task_assignment_service.py`, find the marker it already writes, and have `completed_in_time` return true for rows carrying it; write that test first. If the route writes no distinguishable marker, stop and ask rather than adding a column.
- [ ] **Step 4: Run** `pytest tests/test_chore_ladder.py tests/test_early_bird_rules.py -v` → PASS (old tests unchanged).
- [ ] **Step 5: Commit** `feat(early-bird): cutoff + weekly ladder pure rules`

### Task 3: `week_metrics` — one place the weekly numbers come from

**Files:**
- Modify: `backend/app/services/early_bird_service.py`
- Test: `backend/tests/test_chore_week_metrics.py`

**Interfaces:**
- Consumes: `week_ladder`, `completed_in_time`, `done_early` (Task 2), `covered_rows`.
- Produces: `async def week_metrics(db, cfg, family_id, user_id, monday, now) -> LadderResult` and `def _metrics_from_rows(cfg, rows, monday, now) -> LadderResult`. Returns tier `neutral` when `cfg.enabled` is false, the week is not `week_eligible`, or there are no covered rows. `TAKEN` rows count in `total` as not completed. Rows still `PENDING`/`OVERDUE` count as not completed while the week is in progress (the meter shows "so far"); the ladder tier is only *final* once `now` ≥ Sunday cutoff — expose `final: bool` on the dataclass.

- [ ] **Step 1: Write failing tests** using the existing early-bird fixtures: a 10-chore week at each boundary builds the expected `LadderResult`; disabled family → neutral; taken row counts in total; `final` flips at Sunday cutoff; 4-member exact mirror of the real family (per repo convention).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** reusing `covered_rows` (one query) — no per-row queries. **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(early-bird): week_metrics single source for weekly percentages`

### Task 4: Pay ladder in BankService

**Files:**
- Modify: `backend/app/services/bank_service.py` (`_early_bird_bonus` ~587, `_paycheck_projection` ~607, `release_chore_paycheck` ~857–940)
- Modify: `backend/app/services/early_bird_service.py` (`week_bonus_cents` → ladder-based)
- Test: extend `backend/tests/test_early_bird_paycheck.py`, new `backend/tests/test_chore_ladder_paycheck.py`

**Interfaces:**
- Consumes: `week_metrics` (Task 3).
- Produces: `BankService._ladder_adjust(amount: int, metrics: LadderResult) -> tuple[int, int, int]` returning `(base_cents, bonus_cents, bonus_pct)`: `no_pay` → `(0,0,0)`; `per_task`/`neutral` → `(amount,0,0)`; `bonus` → `(amount, amount*pct//100, pct)`. `_early_bird_bonus` keeps its `(bonus_cents, pct)` return so `release_chore_paycheck` and the receipt path keep working, but derives both from the ladder; `_paycheck_projection` applies the `no_pay` zeroing to `amount` and exposes `ladder_tier`, `completed_pct`, `early_pct` in its dict. Applies only for `CHORE_PAYCHECK_MODES` and `final` weeks; a non-final week projects the in-progress result without zeroing (preview shows "at risk").

- [ ] **Step 1: Write failing tests**: per mode (`chore_proportional`, `chore_gated`, `points_rate`): 5/10 done → amount 0; 6/10 → existing proportional amount; 10/10 with 8/9/10 early → +5/+10/+15 % exactly; 10/10 with 7 early → 0 bonus; `flat` unaffected; Early Bird off → legacy amounts; release path pays same as projection; top-up still pays receipt amount; `chore_gated` does not double-apply (gate then floor yields the same zero, not negative).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** Release path must call the same ladder helper (never recompute inline). **Step 4: Run** `pytest tests/test_early_bird_paycheck.py tests/test_chore_ladder_paycheck.py tests/test_payout_receipts*.py -v` → PASS.
- [ ] **Step 5: Commit** `feat(bank): weekly pay ladder (60 % floor, 100 % early bonus)`

### Task 5: Cutoff expiry and up-for-grabs window

**Files:**
- Modify: `backend/app/services/early_bird_service.py` (`grabbable`, `can_take`, `caller_block`, `take`, `_push_grabs`, `_sweep_reminders` stage logic via `reminder_stage` in rules)
- Modify: the assignment-completion path in `backend/app/services/task_assignment_service.py` (grep `def complete`/kid-complete) and its route for the 409
- Test: extend `backend/tests/test_early_bird_take.py`, new `backend/tests/test_chore_expiry.py`

**Interfaces:**
- Consumes: `DayTimes.cutoff/grab_end`.
- Produces: `grabbable` returns still-open covered chores of today for `cutoff ≤ now < grab_end` (all members' chores, not teens only); `can_take` allows any active, approved family member who is not the owner and whose role is in `allowed_roles`; the "no open own chores" restriction is dropped. A kid completing an owned open chore after cutoff gets HTTP 409 `{"code": "chore_expired"}` via the existing global error handler pattern. After `grab_end` an untaken chore is closed (missed) — no new status; the owner's row stays PENDING/OVERDUE and counts as not completed.

- [ ] **Step 1: Write failing tests**: window boundaries (20:29:59 none, 20:30 listed, 22:29 listed, 22:30 none); any member may take; owner cannot take own; owner completion after cutoff → 409; owner completion before cutoff OK; take locks both rows (existing invariant tests still pass); exempt and bonus templates never listed; Early Bird off → empty list; take after `grab_end` → 409.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** Reuse the `taken` mechanics unchanged. Update the push trigger so the "up for grabs" push fires at `cutoff` instead of deadline.
- [ ] **Step 4: Run** `pytest tests/test_chore_expiry.py tests/test_early_bird_take.py tests/test_early_bird_sweep.py tests/test_early_bird_api.py -v` → PASS (update old tests only where they asserted the 11:00 trigger).
- [ ] **Step 5: Commit** `feat(early-bird): chore cutoff and 20:30-22:30 grab window`

### Task 6: Teen alarms

**Files:**
- Modify: `backend/app/services/early_bird_service.py` (`_sweep_reminders`, new `_alarm`)
- Modify: notification type + localized copy (grep `DEADLINE_SOON` to find the enum, i18n keys, and push mapping); add `CHORE_ALARM`. If the type is a native PG enum, the Task 1 migration must `ALTER TYPE … ADD VALUE` — check first and extend that revision.
- Test: `backend/tests/test_chore_alarms.py`

**Interfaces:**
- Produces: `def alarm_slot(cfg, now) -> Optional[Literal["a1","a2"]]` in `early_bird_rules.py` (true during the 5 minutes starting at `teen_alarm_1/2` local, matching the `*/5` job); `EarlyBirdService._alarm(db, cfg, fam_id, uid, today, slot, since) -> int` sends one `CHORE_ALARM` notification listing the count of pending chores, skipping teens with 0 pending, deduped per slot per day through `PingService._has_ping_since`. TEEN role only. Runs inside the existing `early_bird_sweep` (leader-only, every 5 min).

- [ ] **Step 1: Write failing tests**: slot detection at 15:00/15:04/15:05/19:00; sends to teen with pending chores, not to CHILD/PARENT, not to teen with none; second sweep tick in the same slot sends nothing; Early Bird off → none; ES + EN param rendering.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** + copy (`"Te faltan {n} tareas hoy — vencen a las {cutoff}"` / EN equivalent, singular variant). **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(early-bird): two teen chore alarms a day`

### Task 6b: API exposure

**Files:**
- Modify: `backend/app/schemas/early_bird.py`, `backend/app/services/early_bird_service.py` (`me`, `_teen_view`, `family_overview`), `backend/app/api/routes/early_bird.py` only if a field needs a new route
- Test: extend `backend/tests/test_early_bird_api.py`

**Interfaces:**
- Produces: `/api/early-bird/me` and `/family` add `week: {completed_pct:int, early_pct:int, tier:str, bonus_pct:int, final:bool}` (ints, `int()`-cast for strict mobile clients per CLAUDE.md) and `cutoff`, `grab_end`, `rules_version`.

- [ ] **Step 1: failing API tests** for the new fields, int types, and family-scoping (another family's teen never appears). **Step 2: run** → FAIL. **Step 3: implement**. **Step 4: run** → PASS. **Step 5: Commit** `feat(early-bird): weekly ladder fields on the API`

### Task 7: Frontend — settings, kid meter, copy

**Files:**
- Modify: `frontend/src/lib/earlyBirdSettings.ts`, `frontend/src/pages/parent/settings/family.astro` (Madrugador section), `frontend/src/components/home/EarlyBirdCard.astro`, `frontend/src/lib/earlyBird.ts`
- Test: `frontend/test/earlyBird.test.ts` (+ settings helper tests)

**Interfaces:**
- Consumes: Task 6b fields. Produces: helpers `ladderMessage(week): string` (ES/EN), `validateRulesForm(values)` mirroring backend ranges, settings inputs for cutoff, grab end, two alarm times and streak prize (shown in pesos, sent in cents).

- [ ] **Step 1: Write failing vitest cases**: `ladderMessage` for <60 ("Llevas 52 %: necesitas 60 % para cobrar"), 60–99 (per-task text with how many chores to 100 %), 100 with early tiers (shows next tier), final states; `validateRulesForm` rejects cutoff ≤ deadline and unordered alarms.
- [ ] **Step 2: Run** `cd frontend && npx vitest run test/earlyBird.test.ts` → FAIL. **Step 3: Implement** (copy only in the lib files; ink text on brand fill; `hidden` attribute not class). **Step 4: Run** `npx vitest run` and `npm run check` → PASS.
- [ ] **Step 5: Commit** `feat(early-bird): chore-rules settings + weekly meter`

### Task 8: Docs and full verification

**Files:**
- Modify: `CLAUDE.md` (Early Bird row: cutoff, grab window, ladder, `rules_version`, retired `week_pct`, R1-vs-11:00 note), `logs/SESSION-WORKLOG.md`
- Modify: `docs/superpowers/specs/2026-11-12-chore-rules-v2-design.md` status line → IMPLEMENTED once merged

- [ ] **Step 1:** Run `ruff check app` (zero findings) and all touched backend test files; run `test_ai_gating.py` and `test_migration_early_bird.py`; run the alembic upgrade → downgrade -1 → upgrade round-trip.
- [ ] **Step 2:** Self-review the branch diff adversarially (fan-out review, per repo practice) — money paths first.
- [ ] **Step 3:** Open PR (push → PR → watch CI → merge → sync main). Deploy is the user's step: `! ./scripts/deploy-onprem.sh -y`.
- [ ] **Step 4: Commit** `docs: chore rules v2`
