"""Single-runner gate for scheduled jobs across multiple uvicorn workers.

Previously APScheduler + the overdue sweep were started in every worker's
lifespan, so with `--workers 2` every cron job fired twice. Each worker now calls
``try_acquire_scheduler_leadership`` at startup; exactly one wins a Redis lock and
runs the jobs. The leader renews the lock; if it dies, the TTL lets another worker
take over (on its next restart — see NOTE below).

Each renew/release is guarded by the leader's own token (compare-and-expire /
compare-and-delete via a Lua script) so a worker can NEVER refresh or delete a
lock that a different worker took over after this worker's TTL lapsed.

Fail-CLOSED by default: if Redis stays unreachable after retries we return
leader=False. It used to fail open, which is unsafe with `--workers 2` (prod):
a Redis blip while both workers boot — realistic during the scoped down/up of a
deploy, when redis may still be starting — made BOTH workers leader, so every
cron fired twice concurrently, including the payday and recurring-post sweeps
that move family money. Set ``SCHEDULER_FAIL_OPEN=true`` for a single-instance
deploy that genuinely runs without Redis.

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
"""
import asyncio
import logging
import os
import socket
from typing import Optional, Tuple

import redis.asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger(__name__)

LEADER_KEY = "ftm:scheduler:leader"
LEADER_TTL_SECONDS = 120
# Redis is briefly unavailable during a deploy's scoped down/up, so a single
# failed connect must not decide leadership either way.
ACQUIRE_ATTEMPTS = 5
ACQUIRE_BACKOFF_SECONDS = 6

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
    token = _worker_token()
    last_error: Optional[Exception] = None

    for attempt in range(1, ACQUIRE_ATTEMPTS + 1):
        client = None
        try:
            client = aioredis.from_url(redis_url)
            acquired = await client.set(key, token, nx=True, ex=ttl)
            if acquired:
                return True, client, token
            # A healthy Redis said someone else holds the lock. That is a
            # definitive answer, not an error — do not retry, do not fail open.
            await client.aclose()
            return False, None, None
        except Exception as exc:  # connection/protocol failure only
            last_error = exc
            if client is not None:
                try:
                    await client.aclose()
                except Exception:
                    pass
            if attempt < ACQUIRE_ATTEMPTS:
                await asyncio.sleep(ACQUIRE_BACKOFF_SECONDS)

    if settings.SCHEDULER_FAIL_OPEN:
        logger.warning(
            "Scheduler leadership: Redis unreachable after %d attempts (%s); "
            "SCHEDULER_FAIL_OPEN is set, so this worker will run scheduled jobs. "
            "With more than one worker this can double-fire money-moving sweeps.",
            ACQUIRE_ATTEMPTS, last_error,
        )
        return True, None, None

    logger.error(
        "Scheduler leadership: Redis unreachable after %d attempts (%s); "
        "declining leadership so concurrent workers cannot both run the sweeps. "
        "Scheduled jobs are PAUSED until a worker restarts with Redis reachable.",
        ACQUIRE_ATTEMPTS, last_error,
    )
    return False, None, None


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


async def renew_scheduler_leadership(
    client: Optional["aioredis.Redis"],
    token: Optional[str],
    *,
    key: str = LEADER_KEY,
    ttl: int = LEADER_TTL_SECONDS,
) -> bool:
    """Refresh the lock TTL, but only if we still hold it (token match).

    Returns True while this worker still holds the lock. A False return means
    another worker has taken over (our TTL lapsed) and the caller must stop
    running scheduled jobs — otherwise two workers run them at once, which is
    the exact failure the lock exists to prevent.
    """
    if client is None or token is None:
        return False
    try:
        renewed = await client.eval(_RENEW_LUA, 1, key, token, ttl)
    except Exception:
        # A transient Redis error is not proof the lock was lost; keep running
        # and let the next tick decide.
        return True
    return bool(renewed)


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
