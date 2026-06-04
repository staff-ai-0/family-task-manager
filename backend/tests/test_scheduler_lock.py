"""B2: scheduled jobs must run on exactly ONE worker, not every uvicorn worker.

The leader-election primitive backs that guarantee: the first caller acquires the
Redis lock (becomes the scheduler leader); concurrent callers do not.
"""
from uuid import uuid4

import pytest

from app.core.config import settings
from app.core.scheduler_lock import try_acquire_scheduler_leadership


class TestSchedulerLeaderElection:
    @pytest.mark.asyncio
    async def test_only_one_worker_becomes_leader(self):
        key = "ftm:test:leader:" + uuid4().hex
        a_leader, a_client = await try_acquire_scheduler_leadership(
            settings.REDIS_URL, key=key, ttl=30
        )
        b_leader, b_client = await try_acquire_scheduler_leadership(
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
        first, client = await try_acquire_scheduler_leadership(
            settings.REDIS_URL, key=key, ttl=30
        )
        assert first is True
        # release
        await client.delete(key)
        await client.aclose()
        # a new caller can now take leadership
        second, client2 = await try_acquire_scheduler_leadership(
            settings.REDIS_URL, key=key, ttl=30
        )
        assert second is True
        if client2 is not None:
            await client2.delete(key)
            await client2.aclose()
