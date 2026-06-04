"""Single-runner gate for scheduled jobs across multiple uvicorn workers.

Previously APScheduler + the overdue sweep were started in every worker's
lifespan, so with `--workers 2` every cron job fired twice (double point awards,
double emails, double subscription sweeps). Each worker now calls
``try_acquire_scheduler_leadership`` at startup; exactly one wins a Redis lock and
runs the jobs. The leader renews the lock; if it dies, the TTL lets another worker
take over.

Fail-open: if Redis is unreachable we return leader=True so a single-instance
deploy with no Redis still runs its jobs (the duplicate risk only matters when
multiple workers share a Redis, which is exactly when Redis is up).
"""
import os
import socket
from typing import Optional, Tuple

import redis.asyncio as aioredis

LEADER_KEY = "ftm:scheduler:leader"
LEADER_TTL_SECONDS = 120


async def try_acquire_scheduler_leadership(
    redis_url: str,
    *,
    key: str = LEADER_KEY,
    ttl: int = LEADER_TTL_SECONDS,
) -> Tuple[bool, Optional["aioredis.Redis"]]:
    """Attempt to become the scheduler leader.

    Returns ``(is_leader, client)``. When ``is_leader`` is True the caller owns
    ``client`` and must renew/release it (the client is None in the fail-open
    case). When False the caller must not run scheduled jobs.
    """
    try:
        client = aioredis.from_url(redis_url)
    except Exception:
        return True, None  # fail-open: no Redis → run jobs (single instance)

    try:
        token = f"{socket.gethostname()}:{os.getpid()}"
        acquired = await client.set(key, token, nx=True, ex=ttl)
        if acquired:
            return True, client
        await client.aclose()
        return False, None
    except Exception:
        try:
            await client.aclose()
        except Exception:
            pass
        return True, None  # fail-open on Redis error


async def renew_scheduler_leadership(
    client: "aioredis.Redis", *, key: str = LEADER_KEY, ttl: int = LEADER_TTL_SECONDS
) -> None:
    """Refresh the leader lock TTL so it doesn't expire while this worker lives."""
    try:
        await client.expire(key, ttl)
    except Exception:
        pass


async def release_scheduler_leadership(
    client: Optional["aioredis.Redis"], *, key: str = LEADER_KEY
) -> None:
    """Release the lock on shutdown so another worker can take over immediately."""
    if client is None:
        return
    try:
        await client.delete(key)
    finally:
        try:
            await client.aclose()
        except Exception:
            pass
