"""B2: scheduled jobs must run on exactly ONE worker, not every uvicorn worker.

The leader-election primitive backs that guarantee: the first caller acquires the
Redis lock (becomes the scheduler leader); concurrent callers do not. Renew/release
are token-guarded so a worker can't refresh or delete another worker's lock.
"""
import asyncio
from uuid import uuid4

import pytest

from app.core.config import settings
from app.core.scheduler_lock import (
    try_acquire_scheduler_leadership,
    release_scheduler_leadership,
)


class TestSchedulerLeaderElection:
    @pytest.mark.asyncio
    async def test_only_one_worker_becomes_leader(self):
        key = "ftm:test:leader:" + uuid4().hex
        a_leader, a_client, a_token = await try_acquire_scheduler_leadership(
            settings.REDIS_URL, key=key, ttl=30
        )
        b_leader, b_client, b_token = await try_acquire_scheduler_leadership(
            settings.REDIS_URL, key=key, ttl=30
        )
        try:
            assert a_leader is True, "first caller must win leadership"
            assert b_leader is False, "second caller must NOT also become leader"
        finally:
            if a_client is not None:
                await a_client.delete(key)
                await a_client.aclose()
            if b_client is not None:
                await b_client.aclose()

    @pytest.mark.asyncio
    async def test_leadership_frees_after_release(self):
        key = "ftm:test:leader:" + uuid4().hex
        first, client, token = await try_acquire_scheduler_leadership(
            settings.REDIS_URL, key=key, ttl=30
        )
        assert first is True
        await release_scheduler_leadership(client, token, key=key)
        # a new caller can now take leadership
        second, client2, token2 = await try_acquire_scheduler_leadership(
            settings.REDIS_URL, key=key, ttl=30
        )
        assert second is True
        if client2 is not None:
            await client2.delete(key)
            await client2.aclose()

    @pytest.mark.asyncio
    async def test_release_with_wrong_token_does_not_delete_lock(self):
        """A worker that no longer holds the lock must not be able to delete it."""
        import redis.asyncio as aioredis

        key = "ftm:test:leader:" + uuid4().hex
        leader, client, token = await try_acquire_scheduler_leadership(
            settings.REDIS_URL, key=key, ttl=30
        )
        assert leader is True

        # An impostor with the wrong token must NOT delete our lock.
        impostor = aioredis.from_url(settings.REDIS_URL)
        await release_scheduler_leadership(impostor, "impostor:999", key=key)
        assert (await client.get(key)) is not None, "wrong-token release deleted the lock"

        # Our own (correct-token) release clears it.
        await release_scheduler_leadership(client, token, key=key)
        check = aioredis.from_url(settings.REDIS_URL)
        leftover = await check.get(key)
        await check.aclose()
        assert leftover is None


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

    @pytest.mark.asyncio
    async def test_ignores_fail_open_win_and_keeps_retrying(self, monkeypatch):
        """A SCHEDULER_FAIL_OPEN synthetic win (is_leader=True, client=None)
        must NOT be treated as a real win in the retry loop: this worker
        already lost the startup race to a live leader, so a transient
        Redis outage is not license to install a second scheduler against
        a healthy incumbent — that would double-fire the money-moving
        sweeps this lock exists to prevent. Only a redis-less
        single-instance deploy legitimately fail-opens, and that always
        wins at startup (never enters this loop)."""
        import app.core.scheduler_lock as scheduler_lock_module

        async def _fake_fail_open_win(*args, **kwargs):
            return True, None, None

        monkeypatch.setattr(
            scheduler_lock_module,
            "try_acquire_scheduler_leadership",
            _fake_fail_open_win,
        )

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                scheduler_lock_module.poll_for_leadership(
                    settings.REDIS_URL, interval_seconds=0.1
                ),
                timeout=0.5,
            )

    @pytest.mark.asyncio
    async def test_passes_retrying_true_to_try_acquire(self, monkeypatch):
        """poll_for_leadership must identify itself as a retrying caller so
        try_acquire_scheduler_leadership's fail-closed log message is
        accurate (says 'will keep retrying', not 'PAUSED until restart')."""
        import app.core.scheduler_lock as scheduler_lock_module

        seen_kwargs = {}

        async def _capture(redis_url, **kwargs):
            seen_kwargs.update(kwargs)
            return True, object(), "tok"

        monkeypatch.setattr(
            scheduler_lock_module,
            "try_acquire_scheduler_leadership",
            _capture,
        )

        client, token = await scheduler_lock_module.poll_for_leadership(
            settings.REDIS_URL, interval_seconds=0.05
        )
        assert client is not None
        assert seen_kwargs.get("retrying") is True
