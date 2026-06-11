"""Single-runner gate for scheduled jobs across multiple uvicorn workers.

Previously APScheduler + the overdue sweep were started in every worker's
lifespan, so with `--workers 2` every cron job fired twice. Each worker now calls
``try_acquire_scheduler_leadership`` at startup; exactly one wins a Redis lock and
runs the jobs. The leader renews the lock; if it dies, the TTL lets another worker
take over (on its next restart — see NOTE below).

Each renew/release is guarded by the leader's own token (compare-and-expire /
compare-and-delete via a Lua script) so a worker can NEVER refresh or delete a
lock that a different worker took over after this worker's TTL lapsed.

Fail-open: if Redis is unreachable we return leader=True so a single-instance
deploy with no Redis still runs its jobs.

NOTE: non-leader workers do not re-poll for leadership while running; if the
leader process dies, its lock expires after TTL and the jobs pause until a worker
restarts (acceptable for the daily/5-min sweeps here, and a deploy restarts all
workers). Promote to a periodic re-acquire loop if jobs become latency-critical.
"""
import os
import socket
from typing import Optional, Tuple

import redis.asyncio as aioredis

LEADER_KEY = "ftm:scheduler:leader"
LEADER_TTL_SECONDS = 120

# Only act if WE still hold the lock (stored value == our token).
_RENEW_LUA = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then "
    "return redis.call('expire', KEYS[1], ARGV[2]) else return 0 end"
)
_RELEASE_LUA = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then "
    "return redis.call('del', KEYS[1]) else return 0 end"
)


def _worker_token() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


async def try_acquire_scheduler_leadership(
    redis_url: str,
    *,
    key: str = LEADER_KEY,
    ttl: int = LEADER_TTL_SECONDS,
) -> Tuple[bool, Optional["aioredis.Redis"], Optional[str]]:
    """Attempt to become the scheduler leader.

    Returns ``(is_leader, client, token)``. When ``is_leader`` is True the caller
    owns ``client`` + ``token`` and must renew/release with them (both are None in
    the fail-open case). When False the caller must not run scheduled jobs.
    """
    try:
        client = aioredis.from_url(redis_url)
    except Exception:
        return True, None, None  # fail-open: no Redis -> run jobs (single instance)

    try:
        token = _worker_token()
        acquired = await client.set(key, token, nx=True, ex=ttl)
        if acquired:
            return True, client, token
        await client.aclose()
        return False, None, None
    except Exception:
        try:
            await client.aclose()
        except Exception:
            pass
        return True, None, None  # fail-open on Redis error


async def renew_scheduler_leadership(
    client: Optional["aioredis.Redis"],
    token: Optional[str],
    *,
    key: str = LEADER_KEY,
    ttl: int = LEADER_TTL_SECONDS,
) -> None:
    """Refresh the lock TTL, but only if we still hold it (token match)."""
    if client is None or token is None:
        return
    try:
        await client.eval(_RENEW_LUA, 1, key, token, ttl)
    except Exception:
        pass


async def release_scheduler_leadership(
    client: Optional["aioredis.Redis"],
    token: Optional[str],
    *,
    key: str = LEADER_KEY,
) -> None:
    """Release the lock on shutdown, but only if we still hold it (token match)."""
    if client is None:
        return
    try:
        if token is not None:
            await client.eval(_RELEASE_LUA, 1, key, token)
    finally:
        try:
            await client.aclose()
        except Exception:
            pass
