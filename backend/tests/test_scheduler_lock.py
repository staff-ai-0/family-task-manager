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
