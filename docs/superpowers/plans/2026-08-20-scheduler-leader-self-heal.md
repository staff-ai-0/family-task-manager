# Scheduler Leader Self-Heal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A uvicorn worker that loses the scheduler-leader race at startup must keep retrying in the background and take over once the (possibly stale) lock clears, instead of leaving every cron job — including the weekly auto-shuffle — permanently off until the next deploy.

**Architecture:** Add a retry-poll primitive to `scheduler_lock.py`. Extract the existing "I just became leader" sequence out of `app/main.py`'s inline `if is_leader` branch into shared module-level helpers, so both the immediate-win path and the won-on-retry path run through the exact same code and register the exact same jobs.

**Tech Stack:** Python 3.12, FastAPI lifespan, APScheduler (`AsyncIOScheduler`), redis.asyncio, pytest + pytest-asyncio (real local redis in tests, no mocking — matches existing `test_scheduler_lock.py` style).

**Spec:** `docs/superpowers/specs/2026-08-20-scheduler-leader-self-heal.md`

## Global Constraints

- Never break the single-leader guarantee — at most one worker may run the cron jobs at any time (payday/recurring-post sweeps move real money; double-firing is the exact bug the lock exists to prevent).
- Every cron job must be reachable from both the immediate-win and won-on-retry paths — one source of truth for the job list.
- Tests use real local redis (`settings.REDIS_URL`), consistent with `backend/tests/test_scheduler_lock.py` — no mocking of redis calls.
- Backend lint: `cd backend && ruff check app` must stay clean (CI-enforced, zero-tolerance).
- Leave the PR open, unmerged, when done (per `feedback_auto_mode_overnight` — overnight/unattended dispatch).

---

### Task 1: `poll_for_leadership` retry primitive

**Files:**
- Modify: `backend/app/core/scheduler_lock.py`
- Test: `backend/tests/test_scheduler_lock.py`

**Interfaces:**
- Consumes: existing `try_acquire_scheduler_leadership(redis_url, *, key=LEADER_KEY, ttl=LEADER_TTL_SECONDS) -> Tuple[bool, Optional[Redis], Optional[str]]` (unchanged, already in this file).
- Produces: `poll_for_leadership(redis_url: str, *, key: str = LEADER_KEY, ttl: int = LEADER_TTL_SECONDS, interval_seconds: float = 30.0) -> Tuple["aioredis.Redis", str]` — later tasks (Task 2) import and call this from `app/main.py`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_scheduler_lock.py`, inside a new class below the existing `TestSchedulerLeaderElection`:

```python
class TestPollForLeadership:
    @pytest.mark.asyncio
    async def test_wins_once_stale_lock_expires(self):
        """A worker that lost the startup race keeps retrying and wins once
        the stale key (e.g. left behind by a killed previous deploy
        generation, resurrected via redis AOF replay across a pod recreate)
        expires — instead of leaving the scheduler off for the rest of the
        process life. This is the exact 2026-08-20 incident."""
        from app.core.scheduler_lock import poll_for_leadership

        key = "ftm:test:leader:" + uuid4().hex
        # Simulate the stale lock: someone holds it with a short TTL and
        # never renews (the dead previous-generation worker).
        blocker_leader, blocker_client, _blocker_token = (
            await try_acquire_scheduler_leadership(
                settings.REDIS_URL, key=key, ttl=1
            )
        )
        assert blocker_leader is True
        client, token = None, None
        try:
            client, token = await asyncio.wait_for(
                poll_for_leadership(
                    settings.REDIS_URL, key=key, ttl=30, interval_seconds=0.3
                ),
                timeout=5,
            )
            assert client is not None
            assert token is not None
            assert (await client.get(key)) == token.encode()
        finally:
            if client is not None:
                await release_scheduler_leadership(client, token, key=key)
            await blocker_client.aclose()

    @pytest.mark.asyncio
    async def test_keeps_retrying_while_lock_actively_held(self):
        """Must NOT win while a live leader still holds and could renew the
        lock — poll_for_leadership only takes over once the lock is
        actually free, never by racing a healthy leader."""
        from app.core.scheduler_lock import poll_for_leadership

        key = "ftm:test:leader:" + uuid4().hex
        holder_leader, holder_client, holder_token = (
            await try_acquire_scheduler_leadership(
                settings.REDIS_URL, key=key, ttl=30
            )
        )
        assert holder_leader is True
        try:
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(
                    poll_for_leadership(
                        settings.REDIS_URL, key=key, ttl=30, interval_seconds=0.2
                    ),
                    timeout=1.0,
                )
        finally:
            await release_scheduler_leadership(holder_client, holder_token, key=key)
```

Add `import asyncio` to the top of `backend/tests/test_scheduler_lock.py` (not currently imported there).

- [ ] **Step 2: Run tests to verify they fail**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_scheduler_lock.py -v -k PollForLeadership`
Expected: FAIL with `ImportError: cannot import name 'poll_for_leadership'` (or collection error) — the function doesn't exist yet.

- [ ] **Step 3: Implement `poll_for_leadership`**

In `backend/app/core/scheduler_lock.py`, add after `try_acquire_scheduler_leadership` (i.e. after the function ending at the current line 111 `return False, None, None`):

```python
async def poll_for_leadership(
    redis_url: str,
    *,
    key: str = LEADER_KEY,
    ttl: int = LEADER_TTL_SECONDS,
    interval_seconds: float = 30.0,
) -> Tuple["aioredis.Redis", str]:
    """Retry leadership acquisition until this worker wins.

    A worker that lost the startup race calls this from a background task
    instead of giving up forever (the old behavior — see the module
    docstring's incident note). Re-attempts
    ``try_acquire_scheduler_leadership`` every ``interval_seconds`` until it
    wins, then returns ``(client, token)`` in the exact shape a winning
    startup call would — the caller starts the scheduler + renew loop from
    there via the same path a startup win uses.

    Loops forever by design. The caller creates this as a background task
    and cancels it on shutdown if it never won.
    """
    while True:
        await asyncio.sleep(interval_seconds)
        is_leader, client, token = await try_acquire_scheduler_leadership(
            redis_url, key=key, ttl=ttl
        )
        if is_leader:
            return client, token
```

- [ ] **Step 4: Update the module docstring's stale NOTE**

In `backend/app/core/scheduler_lock.py`, replace the current NOTE paragraph (the one starting `NOTE: non-leader workers do not re-poll...`) with:

```python
NOTE: non-leader workers retry via ``poll_for_leadership`` (run as a
background task from app.main's lifespan) so a lost startup race
self-heals within a few retry intervals instead of leaving the scheduler
off for the rest of the process life. This replaced the old "never
re-poll" behavior after a 2026-08-20 incident: a deploy recreated both the
backend and redis containers back-to-back; redis's AOF persistence
replayed the previous generation's still-unexpired leader key, both new
workers lost the race against it, and — under the old behavior — neither
ever tried again, so the scheduler (all cron jobs, including the weekly
auto-shuffle) silently stayed off for 6 days until a manual restart.
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_scheduler_lock.py -v`
Expected: all pass, including the two new ones and the three pre-existing ones.

- [ ] **Step 6: Lint**

Run: `cd backend && ruff check app/core/scheduler_lock.py`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add backend/app/core/scheduler_lock.py backend/tests/test_scheduler_lock.py
git commit -m "feat(scheduler): add poll_for_leadership retry primitive

Non-leader workers previously gave up forever after losing the startup
race. Adds a retry loop they can run in the background instead."
```

---

### Task 2: Wire the retry path into `app/main.py`

**Files:**
- Modify: `backend/app/main.py` (lifespan function, currently lines 111-305)
- Test: `backend/tests/test_scheduler_retry_wiring.py` (new)

**Interfaces:**
- Consumes: `poll_for_leadership` from Task 1 (`app.core.scheduler_lock`); existing `try_acquire_scheduler_leadership`, `renew_scheduler_leadership`, `release_scheduler_leadership`.
- Produces (module-level in `app/main.py`, used only within this file): `_SchedulerHandles` class, `_register_cron_jobs(scheduler: AsyncIOScheduler) -> None`, `_start_scheduler() -> AsyncIOScheduler`, `_become_leader(handles: "_SchedulerHandles", client, token) -> None`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_scheduler_retry_wiring.py`:

```python
"""Guards the exact 2026-08-20 incident class: a worker that becomes
scheduler leader via the retry path (poll_for_leadership) must end up
running the identical set of cron jobs as one that won immediately — not a
subset. See docs/superpowers/specs/2026-08-20-scheduler-leader-self-heal.md.
"""
import asyncio

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.main import _SchedulerHandles, _become_leader, _register_cron_jobs

EXPECTED_JOB_IDS = {
    "subscription_sweep",
    "pet_decay_sweep",
    "pup_snapshot_sweep",
    "jarvis_sched_sweep",
    "family_bank_payday",
    "family_purge_sweep",
    "auto_shuffle_sweep",
    "recurring_post_sweep",
    "morning_reminder_sweep",
}


def test_register_cron_jobs_attaches_every_job():
    scheduler = AsyncIOScheduler()
    _register_cron_jobs(scheduler)
    assert {job.id for job in scheduler.get_jobs()} == EXPECTED_JOB_IDS


@pytest.mark.asyncio
async def test_become_leader_populates_handles_and_starts_everything():
    """Simulates a worker winning leadership on retry: _become_leader must
    leave it in the exact same state as a worker that won at startup —
    same jobs, renew loop running, handles populated so shutdown can find
    and cancel everything regardless of which path ran."""
    handles = _SchedulerHandles()
    fake_client = object()  # renew loop's first redis call is 60s away —
                             # this test cancels well before that, so a
                             # non-redis object is safe here.
    await _become_leader(handles, fake_client, "fake-token")
    try:
        assert handles.scheduler is not None
        assert {job.id for job in handles.scheduler.get_jobs()} == EXPECTED_JOB_IDS
        assert handles.overdue_task is not None and not handles.overdue_task.done()
        assert handles.renew_task is not None and not handles.renew_task.done()
        assert handles.leader_client is fake_client
        assert handles.leader_token == "fake-token"
    finally:
        handles.scheduler.shutdown(wait=False)
        for task in (handles.overdue_task, handles.renew_task):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_scheduler_retry_wiring.py -v`
Expected: FAIL with `ImportError: cannot import name '_SchedulerHandles'` — none of these exist in `app.main` yet.

- [ ] **Step 3: Extract the shared helpers in `app/main.py`**

Read the current lifespan body first (`backend/app/main.py` lines 111-306) — it inlines, inside `if is_leader:`, 8 sweep-closure defs, 9 `scheduler.add_job(...)` calls, `scheduler.start()`, and the `_renew_leadership_loop` closure + task.

Replace that entire structure. Immediately above `@asynccontextmanager` / `async def lifespan(app: FastAPI):` (i.e. right after `_overdue_sweep_loop`, before the lifespan function), add:

```python
class _SchedulerHandles:
    """Mutable holder for the leader-only background state. Both the
    immediate-win path and the won-on-retry path (poll_for_leadership)
    populate this, so shutdown can find and clean up whichever one ran
    without needing to know in advance which path fired."""

    def __init__(self) -> None:
        self.scheduler: AsyncIOScheduler | None = None
        self.overdue_task: asyncio.Task | None = None
        self.renew_task: asyncio.Task | None = None
        self.leader_client = None
        self.leader_token = None


def _register_cron_jobs(scheduler: AsyncIOScheduler) -> None:
    """Attach every leader-only cron job to `scheduler`. Single source of
    truth shared by both the immediate-win and won-on-retry paths — a job
    added to only one path would silently never run for a worker that wins
    leadership on retry."""

    async def _pet_decay_sweep():
        async with AsyncSessionLocal() as session:
            try:
                n = await PetService.sweep_decay_all(session)
                if n:
                    logger.info("Pet decay sweep notified %d owner(s)", n)
            except Exception:
                logger.exception("Pet decay sweep failed")

    async def _pup_snapshot_sweep():
        async with AsyncSessionLocal() as session:
            try:
                n = await AnalyticsService.write_all_snapshots(session)
                if n:
                    logger.info("PUP snapshot wrote %d family rows", n)
            except Exception:
                logger.exception("PUP snapshot sweep failed")

    async def _jarvis_schedule_sweep():
        async with AsyncSessionLocal() as session:
            try:
                n = await JarvisScheduleService.sweep_due(session)
                if n:
                    logger.info("Jarvis schedule sweep fired %d", n)
            except Exception:
                logger.exception("Jarvis schedule sweep failed")

    async def _family_bank_payday_sweep():
        # Family Bank payday (match → interest → allowance) across families,
        # evaluated in family-local time. Idempotent per family-local week
        # via last_payday_at, so a restart or duplicate tick never
        # double-pays. Runs hourly; the service filters to the local payday
        # weekday + hour>=8 window (spec §D4).
        async with AsyncSessionLocal() as session:
            try:
                from app.services.bank_service import BankService
                n = await BankService.run_payday_sweep(session)
                if n:
                    logger.info("Family Bank payday sweep paid %d kid(s)", n)
            except Exception:
                logger.exception("Family Bank payday sweep failed")

    async def _family_purge_sweep():
        # Hard-delete families soft-deleted longer than the grace window
        # (FamilyDeletionService.PURGE_RETENTION_DAYS). Self-serve family
        # deletion only stamps deleted_at + cancels PayPal synchronously;
        # this sweep does the actual cascade delete + uploads/GCS cleanup.
        # Leader-only (this whole block runs on the elected leader). Each
        # family is purged in isolation so one failure never blocks the rest.
        async with AsyncSessionLocal() as session:
            try:
                from app.services.family_deletion_service import (
                    FamilyDeletionService,
                )
                n = await FamilyDeletionService.purge_expired(session)
                if n:
                    logger.info(
                        "Family purge sweep hard-deleted %d family(ies)", n
                    )
            except Exception:
                logger.exception("Family purge sweep failed")

    async def _auto_shuffle_sweep():
        # Weekly auto-shuffle: families that already use the shuffle get
        # the new week generated without a parent having to remember the
        # button. Idempotent per week (service-level guards); hourly so a
        # Monday spent down self-heals.
        async with AsyncSessionLocal() as session:
            try:
                n = await TaskAssignmentService.auto_shuffle_all(session)
                if n:
                    logger.info("Auto-shuffle sweep created %d assignment(s)", n)
            except Exception:
                logger.exception("Auto-shuffle sweep failed")

    async def _recurring_post_sweep():
        # Auto-post due recurring BUDGET transactions (Actual-Budget
        # schedule parity) — idempotent: posting advances next_due_date.
        async with AsyncSessionLocal() as session:
            try:
                from app.services.budget.recurring_transaction_service import (
                    RecurringTransactionService,
                )
                n = await RecurringTransactionService.post_all_due_all_families(session)
                if n:
                    logger.info("Recurring post sweep created %d transaction(s)", n)
            except Exception:
                logger.exception("Recurring post sweep failed")

    async def _morning_reminder_sweep():
        # 'Tienes N tareas hoy' per member with pending chores due today.
        # Idempotent per local day (DB guard inside the service), so a
        # restart or duplicate tick never double-sends.
        async with AsyncSessionLocal() as session:
            try:
                n = await TaskAssignmentService.send_morning_reminders(session)
                if n:
                    logger.info("Morning reminder sweep sent %d reminder(s)", n)
            except Exception:
                logger.exception("Morning reminder sweep failed")

    scheduler.add_job(run_sweep, "cron", hour=3, minute=0, id="subscription_sweep")
    scheduler.add_job(_pet_decay_sweep, "cron", hour=8, minute=0, id="pet_decay_sweep")
    scheduler.add_job(_pup_snapshot_sweep, "cron", hour=23, minute=30, id="pup_snapshot_sweep")
    scheduler.add_job(_jarvis_schedule_sweep, "cron", minute="*/5", id="jarvis_sched_sweep")
    scheduler.add_job(_family_bank_payday_sweep, "cron", minute=10, id="family_bank_payday")  # hourly
    scheduler.add_job(_family_purge_sweep, "cron", hour=4, minute=0, id="family_purge_sweep")  # daily
    scheduler.add_job(_auto_shuffle_sweep, "cron", minute=25, id="auto_shuffle_sweep")  # hourly
    scheduler.add_job(_recurring_post_sweep, "cron", minute=40, id="recurring_post_sweep")  # hourly
    scheduler.add_job(
        _morning_reminder_sweep,
        "cron",
        hour=7,
        minute=30,
        timezone="America/Mexico_City",
        id="morning_reminder_sweep",
    )


def _start_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    _register_cron_jobs(scheduler)
    scheduler.start()
    return scheduler


async def _become_leader(handles: "_SchedulerHandles", client, token) -> None:
    """Run once this worker holds the leadership lock — via the initial
    startup race or via poll_for_leadership after losing it. Starts the
    overdue sweep, every cron job, and the renewal loop; stores everything
    on `handles` so shutdown finds it regardless of which path ran."""
    from app.core.scheduler_lock import renew_scheduler_leadership

    logger.info("Scheduler leader — starting cron jobs + overdue sweep.")
    handles.leader_client = client
    handles.leader_token = token
    handles.overdue_task = asyncio.create_task(_overdue_sweep_loop())
    handles.scheduler = _start_scheduler()

    async def _renew_leadership_loop():
        while True:
            await asyncio.sleep(60)
            still_leader = await renew_scheduler_leadership(client, token)
            if not still_leader:
                # Another worker took the lock after our TTL lapsed.
                # Keeping the scheduler running here would mean two
                # workers firing the money-moving sweeps at once — the
                # exact thing the lock exists to prevent.
                logger.error(
                    "Scheduler leadership lost — pausing scheduled jobs "
                    "in this worker to avoid double-firing sweeps."
                )
                if handles.scheduler is not None:
                    handles.scheduler.pause()
                return

    handles.renew_task = asyncio.create_task(_renew_leadership_loop())
```

All eight sweep-closure bodies above (`_pet_decay_sweep` through `_morning_reminder_sweep`) are copied verbatim from the current `backend/app/main.py` (lines 149-266) — paste them as-is, do not paraphrase.

- [ ] **Step 4: Rewrite `lifespan()` to use the helpers and add the retry path**

Replace the body of `lifespan()` from `is_leader, leader_client, leader_token = await try_acquire_scheduler_leadership(...)` through the end of the function with:

```python
    is_leader, leader_client, leader_token = await try_acquire_scheduler_leadership(settings.REDIS_URL)

    handles = _SchedulerHandles()
    leadership_poll_task: asyncio.Task | None = None

    if is_leader:
        await _become_leader(handles, leader_client, leader_token)
    else:
        logger.info(
            "Not the scheduler leader at startup — retrying in the "
            "background so a lost race against a stale lock self-heals "
            "without a restart."
        )

        async def _retry_leadership():
            client, token = await poll_for_leadership(settings.REDIS_URL)
            logger.info("Scheduler leadership acquired on retry.")
            await _become_leader(handles, client, token)

        leadership_poll_task = asyncio.create_task(_retry_leadership())

    yield

    # Shutdown
    logger.info("Shutting down API...")
    if leadership_poll_task is not None:
        leadership_poll_task.cancel()
        try:
            await leadership_poll_task
        except asyncio.CancelledError:
            pass
    if handles.scheduler is not None:
        handles.scheduler.shutdown(wait=True)
    for _task in (handles.overdue_task, handles.renew_task):
        if _task is not None:
            _task.cancel()
            try:
                await _task
            except asyncio.CancelledError:
                pass
    await release_scheduler_leadership(handles.leader_client, handles.leader_token)
    await engine.dispose()
```

Update the `from app.core.scheduler_lock import (...)` block near the top of `lifespan()` to also import `poll_for_leadership`:

```python
    from app.core.scheduler_lock import (
        try_acquire_scheduler_leadership,
        poll_for_leadership,
        renew_scheduler_leadership,
        release_scheduler_leadership,
    )
```

- [ ] **Step 5: Run the new test to verify it passes**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_scheduler_retry_wiring.py -v`
Expected: both tests pass.

- [ ] **Step 6: Run the full scheduler-related test set + confirm the app still imports/boots**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_scheduler_lock.py tests/test_scheduler_retry_wiring.py tests/test_health_readiness.py -v`
Expected: all pass. `test_health_readiness.py` imports `app.main` the normal way (via the app's TestClient fixture) — a passing run there confirms the rewritten `lifespan()` doesn't break app startup.

- [ ] **Step 7: Lint**

Run: `cd backend && ruff check app/main.py`
Expected: clean.

- [ ] **Step 8: Local sanity check — confirm leader election still logs correctly**

Run: `podman compose up -d --build backend` then `podman compose logs backend | grep -E "Scheduler leader|Not the scheduler leader"`
Expected: exactly one of the two log lines per worker as before (one worker "Scheduler leader — starting...", the other "Not the scheduler leader..."), confirming the immediate-win path is unchanged. (The retry path only observably differs when the immediate race is lost, which local dev won't naturally reproduce — Task 1's redis-level tests already cover that behavior directly.)

- [ ] **Step 9: Commit**

```bash
git add backend/app/main.py backend/tests/test_scheduler_retry_wiring.py
git commit -m "fix(scheduler): non-leader workers retry instead of giving up forever

Root cause of the 6-day scheduler outage (2026-08-13 to 2026-08-20): a
deploy recreated backend+redis together; redis AOF replayed the previous
generation's still-unexpired leader lock; both new workers lost the race
and, under the old never-re-poll behavior, neither tried again for the
rest of the process life. auto_shuffle_sweep and every other cron job
(payday, purge, pet decay, recurring-post, morning reminders) silently
no-op'd until a manual container restart.

Extracts the leader-branch body into _register_cron_jobs/_start_scheduler/
_become_leader so both the immediate-win and won-on-retry paths run the
identical job set, and adds a background poll_for_leadership retry for
workers that lose the startup race."
```

---

### Task 3: Open the PR (unmerged)

**Files:** none (git/gh operations only)

- [ ] **Step 1: Push the branch**

```bash
git push -u origin HEAD
```

(Confirm you're on a feature branch, not `main`, before pushing — check with `git branch --show-current`; branch from `main` first if this was started on `main`.)

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "fix(scheduler): non-leader workers retry instead of giving up forever" --body-file - <<'EOF'
## Problem
Investigated why the weekly auto-shuffle didn't run this week. Root cause:
the entire cron scheduler (9 jobs, incl. auto_shuffle_sweep,
family_bank_payday, family_purge_sweep) was silently off in prod for 6
days (2026-08-13 → 2026-08-20).

A deploy recreates the whole pod (backend + redis together). Redis's AOF
persistence replayed the previous generation's still-unexpired
`ftm:scheduler:leader` lock into the new redis container; both new workers
lost the `SET NX` race against that resurrected key; and — because
non-leader workers never re-polled — neither ever tried again for the
rest of the process life. Full writeup:
`docs/superpowers/specs/2026-08-20-scheduler-leader-self-heal.md`.

Immediate mitigation (already applied, out of band): manual
`podman restart family_onprem_backend` on prod re-ran the race clean and
restored the scheduler. This PR is the actual fix so it can't recur on the
next deploy.

## Fix
- `poll_for_leadership()` in `scheduler_lock.py`: non-leader workers retry
  every 30s in the background instead of giving up forever.
- `app/main.py`: extracted the leader-branch body into shared helpers
  (`_register_cron_jobs`, `_start_scheduler`, `_become_leader`,
  `_SchedulerHandles`) so a worker that wins leadership on retry ends up
  running the identical job set as one that won at startup.

## Testing
- `test_scheduler_lock.py`: new `TestPollForLeadership` — wins once a
  stale lock's TTL expires; keeps retrying (doesn't win) while a lock is
  actively held. Real local redis, no mocking (matches existing style).
- `test_scheduler_retry_wiring.py` (new): `_register_cron_jobs` attaches
  the exact expected 9 job ids; `_become_leader` populates every
  `_SchedulerHandles` field and leaves the scheduler + renew loop running.
- `test_health_readiness.py` (existing) confirms the rewritten
  `lifespan()` doesn't break app startup.

Dispatched as an overnight/unattended task — left unmerged for review per
usual practice on these.
EOF
```

- [ ] **Step 3: Watch CI**

```bash
gh pr checks --watch
```

If CI fails, fix and push again (do NOT merge regardless of outcome — leave for review).

**Do not run `gh pr merge`.** Stop after CI is green (or after reporting a failure that needs a human decision).
