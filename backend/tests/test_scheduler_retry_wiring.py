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
