# Remove the Evening Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A covered chore is never released to the family; its owner can report it until 23:59 family-local, and "up for grabs" no longer exists anywhere.

**Architecture:** The day's cutoff stays one value served by `early_bird_rules.day_times()`, but it is now the midnight that ends the due day instead of a per-family setting, so every existing consumer (expiry, "completed in time", week finality) follows without a new rule. The grab feature is deleted end to end. Rows a past take produced (`taken`, `taken_from_id`) and the two retired columns stay untouched.

**Tech Stack:** FastAPI + SQLAlchemy (async) + Alembic, pytest; Astro 5 + vitest.

**Spec:** `docs/superpowers/specs/2026-11-25-remove-evening-release-design.md`

## Global Constraints

- The owner can report a covered chore until 23:59 family-local; the first refused instant is 00:00:00 of the next family-local day.
- After midnight the chore behaves as an untaken chore did after the old grab window (409 `chore_expired`, off the kid's lists and gates, a miss for parents, "mark done for kid" still works).
- No schema migration. `families.chore_cutoff` and `families.grab_window_end` stay in the table and in the model, read by nothing.
- Kept exactly as they are: `AssignmentStatus.TAKEN`, `taken_from_id` / `taken_by` / `taken_at`, the locks on both halves of a take, `NotificationType.UP_FOR_GRABS` / `CHORE_TAKEN` and their templates, `ChoreExpiredException`.
- Unchanged: early deadline, per-chore bonus, ladder thresholds, streak, teen alarm times.
- `DAY_END_LABEL = "23:59"` in `early_bird_rules.py` is the only place the display value lives on the backend.
- Copy lives only in the existing copy modules (`lib/earlyBird.ts`, `lib/rulesNotice.ts`, `lib/completeMessages.ts`, `lib/earlyBirdSettings.ts`).
- Backend tests run bare-metal (no local containers): from `backend/`, `TZ=UTC` plus `DATABASE_URL`/`TEST_DATABASE_URL` on the Homebrew Postgres at 5435, `REDIS_URL=redis://localhost:6379/0`, `UPLOADS_ROOT=<scratch>/uploads`, `.venv/bin/pytest -q --no-cov -p no:warnings <files>`. Never the full suite in the foreground.

## Review Focus

1. **Family-local midnight, not UTC.** In America/Mexico_City a completion at 23:59:59 local (05:59:59 UTC next day) succeeds; 00:00:00 local is 409. → Task 1, `test_day_end_is_family_local_midnight`.
2. **An old settings page still open in a browser** posts `chore_cutoff` / `grab_window_end`. The save must succeed and must not bump `rules_version`. → Task 2, `test_retired_fields_are_ignored`.
3. **The take that already happened.** Its owner row stays `taken` (a miss, locked) and the taker's row stays locked and payable. → Task 1, `tests/test_taken_rows.py`.
4. **A late alarm.** A teen alarm at 22:00 or 23:00 (refused before, as "after the cutoff") saves and fires inside its day. → Task 1 `test_late_alarm_fires_inside_its_day`, Task 2 `test_alarm_after_the_old_cutoff_is_accepted`.
5. **Week finality moved.** Sunday 21:00 is no longer final (the kid can still report); Monday 00:00 is. A paycheck projected on Sunday evening is provisional, never floored. → Task 1, `test_final_flips_at_sunday_midnight` and the paycheck projection test.

---

### Task 1: Backend — the day ends at midnight, grabs removed

**Files:**
- Modify: `backend/app/services/early_bird_rules.py`, `backend/app/services/early_bird_service.py`, `backend/app/api/routes/early_bird.py`, `backend/app/schemas/early_bird.py`, `backend/app/services/notification_service.py` (alarm body only if its wording needs it), `backend/app/services/task_assignment_service.py` (docstrings only), `backend/app/main.py:200` (comment)
- Rename: `backend/tests/test_early_bird_take.py` → `backend/tests/test_taken_rows.py`
- Test: `backend/tests/test_chore_ladder.py`, `test_chore_expiry.py`, `test_taken_rows.py`, `test_early_bird_rules.py`, `test_early_bird_sweep.py`, `test_early_bird_api.py`, `test_chore_alarms.py`, `test_chore_week_metrics.py`, `test_chore_ladder_paycheck.py`, `test_early_bird_eleven.py`, `test_task_grading.py`

**Interfaces:**
- Produces: `early_bird_rules.DAY_END_LABEL: str = "23:59"`; `EarlyBirdConfig` without `cutoff` / `grab_end`; `DayTimes(r1, r2, deadline, cutoff)` where `cutoff` is `datetime.combine(day + 1 day, time(0, 0), tzinfo=cfg.tz)`; `reminder_stage(now, t) -> "r1" | "r2" | None`; `EarlyBirdService.run_sweep` result keys `{"reminders", "alarms", "settled", "paid"}`; `/api/early-bird/me` without `grab_end_at`, `grabs`, `take_block`.
- Removed names (nothing may import them): `grab_window_open`, `GRABS_PUSH_WINDOW`, `role_may_take`, `GrabRow`, `EarlyBirdService.{grabbable, can_take, caller_block, _not_eligible, take, grab_list, _push_grabs}`, schemas `GrabItem`, `GrabListItem`.

- [ ] **Step 1: Re-pin the pure-rule tests (failing).** In `test_chore_ladder.py` replace `test_day_times_has_cutoff_and_grab_end` with:

```python
def test_day_times_cutoff_is_the_midnight_ending_the_day():
    t = day_times(cfg(), D)
    assert t.cutoff == datetime.combine(D + timedelta(days=1), time(0, 0), tzinfo=TZ)
    assert not hasattr(t, "grab_end")
```

  Drop `cutoff=` / `grab_end=` from every `EarlyBirdConfig(...)` in the test files listed above. In `test_early_bird_rules.py` delete the `GRABS_PUSH_WINDOW` and `"grabs"` stage assertions and assert `reminder_stage(t.cutoff, t) is None`. In `test_chore_alarms.py` replace the clamp test with `test_late_alarm_fires_inside_its_day` (alarm_2 = 23:00 → `alarm_slot` is `"a2"` at 23:00 and 23:29, `None` at 23:30). In `test_chore_week_metrics.py` replace `test_final_flips_at_sunday_cutoff_not_deadline` with `test_final_flips_at_sunday_midnight` (Sunday 21:00 → `final is False`; Monday 00:00 → `final is True`) and move the `AFTER` constant to Monday 00:30.

- [ ] **Step 2: Re-pin the expiry tests (failing).** In `test_chore_expiry.py` delete every test about the grab list, takes and the grabs push, and pin:

```python
@pytest.mark.parametrize("hh,mm,ss", [(20, 30, 0), (21, 5, 0), (23, 59, 59)])
async def test_owner_completion_any_time_on_the_due_day_ok(ctx, hh, mm, ss): ...   # status COMPLETED

async def test_owner_completion_after_midnight_expired(ctx): ...                   # day+1 00:00:00 -> ChoreExpiredException

async def test_day_end_is_family_local_midnight(ctx): ...
    # America/Mexico_City: now = day+1 05:59:59 UTC completes; day+1 06:00:00 UTC raises

async def test_evening_completion_counts_for_the_ladder(ctx): ...                  # completed 21:00 -> completed_in_time True

async def test_todays_open_chore_in_the_evening_still_blocks_bonus(ctx): ...       # 21:00, was "does not block"
```

  Keep (re-timed past midnight where they said "after cutoff"): yesterday's chore does not block bonus/gigs, Atrasadas / waiting count / kiosk exclude expired, exempt and bonus never expire, Early Bird off never expires, inactive day never 409, HTTP 409 code, mark-done-for-kid after expiry, the single-`now` test, the gate query-count tests. Sent-back rows: a redo the same evening counts in time; a redo the NEXT day is allowed and counts late.

- [ ] **Step 3: Keep the history invariants without `take()`.** `git mv` the take test file to `test_taken_rows.py`. Add a helper that builds what a take left behind, and delete the tests of the take action itself (who may take, window, races, notification language):

```python
async def _taken_pair(db, owner, taker, tpl, day):
    """Owner row TAKEN (taken_by/taken_at set) + taker row PENDING with taken_from_id."""
```

  Surviving tests, all through `_taken_pair`: owner cannot complete a taken row, `mark_done_for_kid` rejects it, reshuffle keeps both rows, a taken row counts as a miss, the taker completes and earns ordinary points, `taken` serializes on the payout endpoints, neither half can be patched/moved/cancelled/deleted, the taker's completed row can still be reopened.

- [ ] **Step 4: Re-pin the sweep and API tests (failing).** `test_early_bird_sweep.py`: delete the grabs tests, assert `set(res) == {"reminders", "alarms", "settled", "paid"}`, and add `test_sweep_sends_nothing_at_the_old_cutoff` (an open chore at 20:30 → no `up_for_grabs` row). `test_early_bird_api.py`: delete the take/grabs tests; `/me` key set loses `grabs`, `take_block`, `grab_end_at`; `cutoff_at` is the next family-local midnight; add:

```python
async def test_grab_endpoints_are_gone(client, ...):
    assert (await client.get("/api/early-bird/grabs", headers=h)).status_code == 404
    assert (await client.post(f"/api/early-bird/grabs/{a.id}/take", headers=h)).status_code == 404
```

- [ ] **Step 5: Run them to see them fail.** The files of steps 1–4. Expected: collection/attribute errors and assertion failures, nothing else.

- [ ] **Step 6: Implement.** `early_bird_rules.py` and `early_bird_service.py` per the Interfaces block; `alarm_slot` window is `[start, start + ALARM_WINDOW)`; `_alarm` passes `params={"n": n, "cutoff": DAY_END_LABEL}`; the two routes and the two schemas go. Update the docstrings that still describe a release ("the family's now", "up for grabs").

- [ ] **Step 7: Run the step-5 files plus `test_early_bird_bonus.py test_ping_rules.py test_kiosk_prefs.py test_oversight_today_fields.py test_family_cup.py`.** Expected: all pass. `ruff check app` clean. `grep -rn -E "grab_window_open|role_may_take|grabbable|GrabRow|_push_grabs" backend/app` prints nothing.

- [ ] **Step 8: Mutation check.** Put `time(20, 30)` back as the cutoff in `day_times`; `test_owner_completion_any_time_on_the_due_day_ok` and `test_final_flips_at_sunday_midnight` must fail. Revert.

- [ ] **Step 9: Commit** — `feat(chores): a chore stays its owner's until midnight; remove up for grabs`.

### Task 2: Backend — settings, rules snapshot, rules-version bump

**Files:**
- Modify: `backend/app/schemas/family.py`, `backend/app/services/family_service.py`, `backend/app/services/rules_service.py`, `backend/app/schemas/rules.py`, `backend/app/models/family.py` (comment: both columns RETIRED)
- Create: `backend/migrations/versions/2026_11_25_remove_evening_release.py` (revision `remove_evening_release`, down_revision = the current single head; confirm with `alembic heads`)
- Test: `backend/tests/test_chore_rules_config.py`, `test_rules_acceptance.py`, `test_rules_announce.py`, `test_early_bird_model.py`, `test_migration_early_bird.py`

**Interfaces:**
- Consumes: `early_bird_rules.DAY_END_LABEL`.
- Produces: `RulesSnapshot` keys `{version, deadline, day_end, alarm_1, alarm_2, streak_cents, chore_bonus_pct, floor_pct, bonus_tiers}`; `FamilyUpdate` / `FamilyResponse` without `chore_cutoff` / `grab_window_end`.

- [ ] **Step 1: Failing tests.** `test_chore_rules_config.py`: response has no `chore_cutoff` / `grab_window_end`; delete the cutoff and grab-window validation cases; keep "alarm 1 before alarm 2"; add:

```python
async def test_retired_fields_are_ignored(client, auth_headers, test_family):
    r = await _patch(client, auth_headers, chore_cutoff="21:00", grab_window_end="23:00")
    assert r.status_code == 200 and r.json()["rules_version"] == 1
    assert "chore_cutoff" not in r.json() and "grab_window_end" not in r.json()

async def test_alarm_after_the_old_cutoff_is_accepted(client, auth_headers):
    r = await _patch(client, auth_headers, teen_alarm_1="21:00", teen_alarm_2="23:00")
    assert r.status_code == 200 and r.json()["rules_version"] == 2
```

  `test_rules_acceptance.py`: both key-set assertions use the Produces set and `rules["day_end"] == "23:59"`. `test_rules_announce.py`: every `chore_cutoff="21:00"` used as "a rule changed" becomes `teen_alarm_2="19:30"`. `test_early_bird_model.py:126`: drop the two retired kwargs.

- [ ] **Step 2: Migration test (failing)** in `test_migration_early_bird.py`, same harness as the file's other tests: at `remove_evening_release` a family seeded with `rules_version = 3` reads 4; after `downgrade -1` it reads 3 again and a family at 1 stays 1.

- [ ] **Step 3: Run; expect failures.**

- [ ] **Step 4: Implement.** Remove the two fields, their validators and serializer names from the schemas; in `FamilyService.update_family` remove them from the NOT-NULL list, the merged order checks (only `teen_alarm_1 < teen_alarm_2` remains) and the rules-version trigger. Snapshot per Produces. Migration: `UPDATE families SET rules_version = rules_version + 1` / `GREATEST(1, rules_version - 1)`.

- [ ] **Step 5: Run the task's files plus `test_family_export*.py` (snapshot export) and the alembic round-trip** (`upgrade head` → `downgrade -1` → `upgrade head` on the test DB). Expected: pass; `ruff check app` clean.

- [ ] **Step 6: Commit** — `feat(rules): drop the cutoff and grab settings; re-ask acceptance`.

### Task 3: Frontend — no grabs, no cutoff settings, new copy

**Files:**
- Delete: `frontend/src/components/home/UpForGrabs.astro`, `frontend/src/components/home/GrabsCard.astro`
- Modify: `frontend/src/components/home/KidHome.astro`, `frontend/src/pages/parent/index.astro`, `frontend/src/pages/dashboard.astro` (comment), `frontend/src/components/home/EarlyBirdCard.astro`, `frontend/src/lib/earlyBird.ts`, `frontend/src/lib/completeMessages.ts`, `frontend/src/lib/earlyBirdSettings.ts`, `frontend/src/pages/parent/settings/family.astro`, `frontend/src/lib/rulesNotice.ts`, `frontend/src/types/api.ts` (if it types the removed fields)
- Test: `frontend/test/earlyBird.test.ts`, `early-bird-settings.test.ts`, `rulesNotice.test.ts`, `complete-route.test.ts`

**Interfaces:**
- Consumes: `/api/early-bird/me` and `RulesSnapshot` as produced by Tasks 1–2.
- Produces: `CardState = "early" | "on_track" | "before_cutoff" | "missed" | "idle"`; `EarlyBirdView` without `grabs` / `takeBlock`; `RulesValues` with `day_end` instead of `cutoff` / `grab_end`; `EarlyBirdField` / `RulesField` without `"cutoff"` / `"grabEnd"`.

- [ ] **Step 1: Failing tests.** Exact copy to pin:

| Where | ES | EN |
|---|---|---|
| rules line (after the early-deadline line) | `Fin del día: tienes hasta las ${day_end} para marcar tus tareas como hechas; después cuentan como no hechas.` | `End of day: you have until ${day_end} to mark your chores as done; after that they count as not done.` |
| card headline, state `before_cutoff` | `Tus tareas de hoy siguen abiertas hasta la medianoche` | `Today's chores stay open until midnight` |
| `chore_expired` | `El día de esta tarea ya terminó. Si la hiciste, pide a tus papás que la marquen.` | `This chore's day is over. If you did it, ask a parent to mark it.` |
| alarms validation message | `Las alarmas van de 06:00 a 23:00, en pasos de 5 minutos, la primera antes que la segunda.` | `Alarms run from 06:00 to 23:00 in 5-minute steps, the first before the second.` |

  `earlyBird.test.ts`: delete the grab/take suites; `earlyBirdView` is `null` whenever `applies` is false; with an open chore past the deadline the state is `before_cutoff` and the countdown runs to `cutoff_at`; no state is ever `late`. `early-bird-settings.test.ts`: the form has no cutoff/grabEnd; alarms at 21:00/23:00 validate; the payload has no `chore_cutoff` / `grab_window_end`. `rulesNotice.test.ts`: the two old lines are gone, the new one renders from `day_end`. Add a source guard: no file under `frontend/src` contains `early-bird/grabs`.

- [ ] **Step 2: Run `npx vitest run test/earlyBird.test.ts test/early-bird-settings.test.ts test/rulesNotice.test.ts test/complete-route.test.ts`; expect failures.**

- [ ] **Step 3: Implement** per Files and Interfaces. The settings hint that said open chores "go up for grabs" now says they count as not done after midnight.

- [ ] **Step 4: Run the whole vitest suite, `npm run check`, `npm run build`.** Expected: all green (the visual, contrast and no-native-dialogs guards included).

- [ ] **Step 5: Commit** — `feat(ui): remove up for grabs and the cutoff settings`.

### Task 4: Docs

**Files:**
- Modify: `docs/USER_GUIDE_ES.md`, `docs/USER_GUIDE_EN.md` (Early Bird section: the cutoff and up-for-grabs bullets become one "end of day" bullet; alarms, ladder, evening-chore and mark-done bullets lose the word cutoff), `CLAUDE.md` (Early bird row, current state), `docs/superpowers/specs/2026-11-12-chore-rules-v2-design.md` (one "superseded by" line under "As built")

- [ ] **Step 1: Edit.** The guide must not promise anything the code no longer does: `grep -n -i -E "para tomar|up for grabs|hora de corte|evening cutoff" docs/USER_GUIDE_*.md` prints nothing afterwards.
- [ ] **Step 2: `npx vitest run` in `frontend/`** (the guide pages render from these files). Expected: green.
- [ ] **Step 3: Commit** — `docs: chores stay the owner's until midnight`.
