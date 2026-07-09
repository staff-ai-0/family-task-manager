"""Redis pub/sub fan-out for real-time SSE streams (family chat + DM).

Replaces the old 2-second DB-poll loop with event-driven delivery: creating a
message PUBLISHes a lightweight signal to a family/thread-scoped Redis channel,
and each SSE generator SUBSCRIBEs and wakes the instant that signal lands, then
re-reads the DB (the source of truth) so ordering, dedup, read-state and
reactions stay byte-for-byte identical to the old poll. A bounded fallback DB
poll still runs on every stream so a dropped publish (Redis blip, cross-worker
race, subscribe/publish gap) can never silently lose a message.

Everything here is best-effort. If Redis is unreachable, ``publish`` is a no-op
and ``subscribe`` returns ``None``; the SSE generator then degrades to a pure
fallback poll. The write path (message persistence) already committed before we
publish, so a Redis outage must never fail a send.

Redis client: an event-loop-aware singleton, mirroring
``app.services.fx_service._get_redis`` — one pooled client per running loop so we
don't leak connection pools, and so pytest's function-scoped loops rebind cleanly
instead of hitting "Event loop is closed".
"""
import asyncio
import json
import logging
from typing import Any, Optional

import redis.asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger(__name__)

_redis_client: Optional["aioredis.Redis"] = None
_redis_client_loop = None


def get_redis() -> "aioredis.Redis":
    """Return the shared pub/sub Redis client, (re)bound to the running loop."""
    global _redis_client, _redis_client_loop
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None
    if _redis_client is None or _redis_client_loop is not current_loop:
        _redis_client = aioredis.from_url(
            settings.REDIS_URL, decode_responses=True
        )
        _redis_client_loop = current_loop
    return _redis_client


def chat_channel(family_id: Any) -> str:
    return f"ftm:chat:{family_id}"


def dm_channel(thread_id: Any) -> str:
    return f"ftm:dm:{thread_id}"


async def publish(channel: str, payload: dict) -> None:
    """Best-effort publish; never raises.

    Message persistence has already committed by the time we get here, so a
    Redis failure must not propagate to the caller — real-time delivery is a
    bonus layered on top of the SSE fallback poll.
    """
    try:
        await get_redis().publish(channel, json.dumps(payload))
    except Exception:
        logger.debug("message_bus publish to %s failed", channel, exc_info=True)


async def subscribe(channel: str):
    """Subscribe to ``channel``; return the live ``PubSub`` or ``None``.

    The caller owns the returned object and must close it with ``close_pubsub``.
    Returning ``None`` on any Redis error (instead of raising) lets the SSE
    generator fall back to a pure DB poll without special-casing.
    """
    try:
        pubsub = get_redis().pubsub()
        await pubsub.subscribe(channel)
        return pubsub
    except Exception:
        logger.debug("message_bus subscribe to %s failed", channel, exc_info=True)
        return None


async def wait_for_event(pubsub, timeout: float) -> bool:
    """Wait up to ``timeout`` seconds for a published message on ``pubsub``.

    Returns ``True`` if a message arrived (the caller should then re-read the
    source of truth), ``False`` on timeout. On a ``None`` pubsub (Redis down) or
    any Redis error it sleeps ``timeout`` and returns ``False`` so the caller
    keeps servicing its heartbeat + fallback-poll cadence at a steady tick.
    """
    if pubsub is None:
        await asyncio.sleep(timeout)
        return False
    try:
        msg = await pubsub.get_message(
            ignore_subscribe_messages=True, timeout=timeout
        )
        return msg is not None
    except Exception:
        logger.debug("message_bus wait_for_event failed", exc_info=True)
        await asyncio.sleep(timeout)
        return False


async def close_pubsub(pubsub, channel: str) -> None:
    """Unsubscribe + release the pubsub connection. Never raises."""
    if pubsub is None:
        return
    try:
        await pubsub.unsubscribe(channel)
    except Exception:
        pass
    try:
        await pubsub.aclose()
    except Exception:
        pass
