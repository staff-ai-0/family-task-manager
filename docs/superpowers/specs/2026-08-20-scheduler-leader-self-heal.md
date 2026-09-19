# Scheduler leader self-heal — design spec

**Date:** 2026-08-20
**Trigger:** User asked why the weekly shuffle didn't run automatically. Investigation (systematic-debugging) found the entire cron scheduler — not just shuffle — had been silently off in prod for 6 days.

## Problem

`backend/app/core/scheduler_lock.py` elects exactly one of prod's 2 uvicorn
workers as "scheduler leader" via a Redis `SET NX EX` lock
(`ftm:scheduler:leader`, TTL 120s, renewed every 60s). Only the leader runs
`app/main.py`'s `AsyncIOScheduler` (9 cron jobs, incl. `auto_shuffle_sweep`)
and the overdue-sweep loop. By design, a worker that loses the startup race
**never tries again** — see the old module docstring's NOTE, which called
this "acceptable... a deploy restarts all workers."

That assumption breaks when the lock survives the very restart meant to
clear it:

1. `deploy-onprem.sh` recreates the whole pod (`podman compose down` then
   `up`) — backend **and** redis both get new containers.
2. `family_onprem_redis` runs `--appendonly yes` against a persistent
   volume (`redis_data`). AOF replay on the new redis container restores
   whatever the old container held — including `ftm:scheduler:leader`,
   with its TTL still counting down (the pre-deploy leader was renewing
   every 60s until killed, so up to ~120s of lockout can survive).
3. Both new workers start within that window, both lose the `SET NX` race
   against the resurrected key, and — because non-leaders don't re-poll —
   the scheduler stays off for the rest of that container's life. Nothing
   retries it until the *next* deploy.

**Observed impact (2026-08-13 21:06 CST → 2026-08-20 01:20 CST, ~6 days):**
zero log lines for any of the 9 cron jobs. `auto_shuffle_sweep` (hourly),
`family_bank_payday` (hourly — real money), `family_purge_sweep` (daily),
`pet_decay_sweep`, `pup_snapshot_sweep`, `jarvis_sched_sweep`,
`recurring_post_sweep`, `morning_reminder_sweep`, and `subscription_sweep`
all silently no-op'd. User had to shuffle manually via the UI.

Immediate mitigation already applied out-of-band: `podman restart
family_onprem_backend` on 2026-08-20 (lock key was naturally empty by then,
so the race re-ran clean). This spec is the actual fix so it can't recur.

## Goals

- A worker that loses the leader race at startup must still be able to
  become leader later, once the stale lock naturally expires — without
  requiring a restart.
- No change to the single-leader guarantee: at most one worker runs the
  cron jobs at any time (this is what stops the payday/recurring-post
  sweeps from double-firing).
- Every cron job must be reachable from *either* path (initial-leader or
  won-on-retry) — a job wired into only one would silently never run for
  a worker that wins on retry. This is a real regression risk during the
  refactor, since the job list currently lives inline inside the
  initial-leader branch.

## Non-goals

- Don't fix the AOF-survives-recreate behavior itself (redis persistence
  is intentional — payday/recurring-post idempotency guards elsewhere
  depend on redis/DB state surviving restarts). The retry loop makes the
  stale-key race harmless regardless of *why* the key outlived the
  process that set it, so there's no need to also chase root-causing the
  AOF angle.
- Don't add alerting/monitoring for "scheduler has no leader" — worth a
  future ticket, out of scope for this fix.

## Design

Add `poll_for_leadership(redis_url, *, key, ttl, interval_seconds=30.0)` to
`scheduler_lock.py`: loops `sleep(interval_seconds)` →
`try_acquire_scheduler_leadership(...)` until it wins, then returns
`(client, token)` — the same shape a winning startup call returns. 30s
default means a worst-case 120s-TTL stale lock clears within ~4 attempts.

In `app/main.py`, extract the current leader-branch body (job closures +
`scheduler.add_job(...)` calls + `scheduler.start()` + the renew loop) out
of the inline `if is_leader` block into module-level helpers shared by
both paths:

- `_register_cron_jobs(scheduler)` — attaches all 9 jobs. Single source of
  truth so both paths always register the identical job set.
- `_start_scheduler()` — builds + starts an `AsyncIOScheduler` via
  `_register_cron_jobs`.
- `_SchedulerHandles` — mutable holder (scheduler/overdue_task/renew_task/
  leader_client/leader_token) so shutdown can find whichever path actually
  ran, since it's no longer known at shutdown-code-writing time whether
  the initial branch or the retry branch populated it.
- `_become_leader(handles, client, token)` — the shared "I just won
  leadership" sequence: starts the overdue loop, starts the scheduler,
  starts the renew loop. Called from the startup path immediately, or from
  the retry path once `poll_for_leadership` resolves.

`lifespan()`: on `is_leader` at startup, call `_become_leader` as today. On
`not is_leader`, spawn a background task that awaits
`poll_for_leadership(...)` then calls `_become_leader` — instead of just
logging and doing nothing. Shutdown cancels that poll task too (in
addition to the existing overdue/renew/scheduler cleanup), guarded the
same way (`if task is not None: cancel(); await; except CancelledError`).

## Testing

- `scheduler_lock.py`: `poll_for_leadership` against real local redis —
  (a) wins once a stale lock's TTL naturally expires, (b) keeps retrying
  (doesn't win) while a lock is actively held. Mirrors the existing
  `TestSchedulerLeaderElection` style (real redis, no mocking).
- `main.py`: `_register_cron_jobs` attaches the exact expected 9 job ids
  (regression guard for "a job only wired into one path"). `_become_leader`
  populates every `_SchedulerHandles` field and leaves the scheduler +
  both tasks running (using a fake client — renew loop's first real redis
  call is 60s away, safely past the test's cancel).

## Rollout

Standard PR flow: branch → tests → PR → CI → **leave unmerged for review**
(per `feedback_auto_mode_overnight` — this was dispatched as an overnight
task). Prod is already unblocked by the manual restart; this PR prevents
recurrence on the *next* deploy, not urgent to rush to prod tonight.
