"""Guards the exact 2026-08-20 incident class: a worker that becomes
scheduler leader via the retry path (poll_for_leadership) must end up
running the identical set of cron jobs as one that won immediately — not a
subset. See docs/superpowers/specs/2026-08-20-scheduler-leader-self-heal.md.
"""
import asyncio
import logging
from uuid import uuid4

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import app.core.scheduler_lock as scheduler_lock_module
import app.main as main_module
from app.core.config import settings as app_settings
from app.core.scheduler_lock import (
    release_scheduler_leadership,
    try_acquire_scheduler_leadership,
)
from app.main import (
    _SchedulerHandles,
    _become_leader,
    _register_cron_jobs,
    _retry_leadership,
)

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
        # _become_leader itself never awaits, so without a yield point here
        # neither task has been scheduled to run yet and `done()` would be
        # False regardless of whether the coroutine is even valid. Give both
        # a tick to reach their first await point (_overdue_sweep_loop sleeps
        # 30s before its first DB query, so this doesn't touch the DB).
        await asyncio.sleep(0)
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


@pytest.mark.asyncio
async def test_retry_leadership_wins_after_losing_startup_race_and_starts_everything(
    monkeypatch,
):
    """End-to-end reproduction of the actual incident this PR fixes: a worker
    that lost the startup leader race (a stale lock is still held) keeps
    retrying via _retry_leadership and, once the stale lock expires, ends up
    running the full job set — not left permanently without a scheduler.

    This exercises _retry_leadership itself (not just its two constituent
    pieces separately), so it would catch a bug in its own two-line body —
    e.g. forgetting to call _become_leader, or awaiting the wrong thing.
    """
    key = "ftm:test:leader:" + uuid4().hex
    # Simulate the stale lock from a dead previous-generation worker.
    blocker_leader, blocker_client, _blocker_token = await try_acquire_scheduler_leadership(
        app_settings.REDIS_URL, key=key, ttl=1
    )
    assert blocker_leader is True

    # _retry_leadership hardcodes poll_for_leadership's defaults (the
    # production LEADER_KEY, 120s TTL, 30s poll interval) — too slow for a
    # test and it would contend with the real prod lock key. Redirect the
    # module-level poll_for_leadership it looks up (via its own internal
    # `from app.core.scheduler_lock import poll_for_leadership`) to a
    # wrapper that points the SAME real function at our test key with a
    # fast interval. This does not mock redis or leadership behavior at
    # all — only which key/timing is used — so the win is still a real
    # SET NX EX race against real local redis.
    real_poll = scheduler_lock_module.poll_for_leadership

    async def _fast_poll(redis_url, **_ignored_defaults):
        return await real_poll(redis_url, key=key, ttl=30, interval_seconds=0.3)

    monkeypatch.setattr(scheduler_lock_module, "poll_for_leadership", _fast_poll)

    handles = _SchedulerHandles()
    try:
        await asyncio.wait_for(
            _retry_leadership(handles, app_settings.REDIS_URL), timeout=5
        )
        assert handles.scheduler is not None
        assert {job.id for job in handles.scheduler.get_jobs()} == EXPECTED_JOB_IDS
        await asyncio.sleep(0)  # let the freshly-created tasks reach their first await
        assert handles.overdue_task is not None and not handles.overdue_task.done()
        assert handles.renew_task is not None and not handles.renew_task.done()
        assert handles.leader_client is not None
        assert handles.leader_token is not None
    finally:
        if handles.scheduler is not None:
            handles.scheduler.shutdown(wait=False)
        for t in (handles.overdue_task, handles.renew_task):
            if t is not None:
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass
        if handles.leader_client is not None:
            await release_scheduler_leadership(
                handles.leader_client, handles.leader_token, key=key
            )
        await blocker_client.aclose()


@pytest.mark.asyncio
async def test_retry_leadership_catches_exception_instead_of_propagating(
    monkeypatch, caplog
):
    """If the wrapped call raises (most plausibly _become_leader's
    scheduler.start()), _retry_leadership must catch it and log at ERROR —
    not leave it unretrieved on the task (silent, no log) and not re-raise
    it out toward the caller, which in production would propagate out of
    lifespan() at shutdown and skip engine.dispose()."""

    async def _instant_win(*args, **kwargs):
        return object(), "fake-token"

    async def _boom(*args, **kwargs):
        raise RuntimeError("boom: simulated _become_leader failure")

    monkeypatch.setattr(scheduler_lock_module, "poll_for_leadership", _instant_win)
    monkeypatch.setattr(main_module, "_become_leader", _boom)

    handles = _SchedulerHandles()
    with caplog.at_level(logging.ERROR):
        # Must return normally — the exception must not propagate.
        await _retry_leadership(handles, "redis://localhost:6379/0")

    assert any(
        "Scheduler leadership retry failed" in r.getMessage()
        for r in caplog.records
    ), "an exception inside _retry_leadership must be logged, not swallowed silently"
    # And it must genuinely not have become leader.
    assert handles.scheduler is None


@pytest.mark.asyncio
async def test_retry_leadership_propagates_cancellation(monkeypatch):
    """CancelledError must NOT be swallowed like other exceptions — shutdown
    cancels this task and awaits it expecting CancelledError to re-raise
    (see lifespan()'s shutdown block)."""

    async def _never_wins(*args, **kwargs):
        await asyncio.sleep(100)

    monkeypatch.setattr(scheduler_lock_module, "poll_for_leadership", _never_wins)

    handles = _SchedulerHandles()
    task = asyncio.create_task(_retry_leadership(handles, "redis://localhost:6379/0"))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
