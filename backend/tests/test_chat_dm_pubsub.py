"""Redis pub/sub delivery for chat + DM SSE streams.

Covers the migration off the 2s DB poll:
  * message_bus publish -> subscriber receives (and times out cleanly on silence)
  * publish is best-effort (never raises, even if Redis blows up)
  * the SSE generators deliver a new message near-instantly via a publish
  * the bounded fallback poll still delivers when the publish is dropped

The stream generators read the DB through ``app.core.database.AsyncSessionLocal``
(bound to the app DB), while the test writes go to the separate test DB via the
``db_session`` fixture. So for the integration tests we monkeypatch
``AsyncSessionLocal`` onto the test engine — the generator then reads the same DB
the test writes to. Redis is real and shared.
"""
import asyncio

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.core.database as db_module
from app.core import message_bus
from app.services import dm_service, family_chat_service
from app.services.dm_service import DMService
from app.services.family_chat_service import FamilyChatService


# ─── message_bus unit tests ──────────────────────────────────────────────


class TestMessageBus:
    async def test_publish_then_subscriber_receives(self):
        channel = message_bus.chat_channel("pubsub-roundtrip-fam")
        pubsub = await message_bus.subscribe(channel)
        if pubsub is None:
            pytest.skip("Redis unavailable")
        try:
            # Settle the subscription: Redis pub/sub has no buffering, so a
            # PUBLISH before the SUBSCRIBE is registered server-side is lost.
            # One read drains the subscribe ack and forces the round-trip
            # (this is exactly what the live SSE loop does before it publishes).
            assert await message_bus.wait_for_event(pubsub, timeout=0.5) is False
            await message_bus.publish(channel, {"id": "abc"})
            woke = await message_bus.wait_for_event(pubsub, timeout=2.0)
            assert woke is True
        finally:
            await message_bus.close_pubsub(pubsub, channel)

    async def test_wait_times_out_when_no_publish(self):
        channel = message_bus.chat_channel("pubsub-silent-fam")
        pubsub = await message_bus.subscribe(channel)
        if pubsub is None:
            pytest.skip("Redis unavailable")
        try:
            woke = await message_bus.wait_for_event(pubsub, timeout=0.3)
            assert woke is False
        finally:
            await message_bus.close_pubsub(pubsub, channel)

    async def test_publish_is_best_effort_and_never_raises(self, monkeypatch):
        def _boom():
            raise RuntimeError("redis down")

        monkeypatch.setattr(message_bus, "get_redis", _boom)
        # Must not raise — the write path already committed.
        await message_bus.publish(message_bus.chat_channel("x"), {"id": "y"})

    async def test_wait_with_none_pubsub_returns_false(self):
        # Redis-down degradation path: no pubsub -> sleep + False (fallback poll).
        woke = await message_bus.wait_for_event(None, timeout=0.05)
        assert woke is False


# ─── stream integration tests ────────────────────────────────────────────


@pytest_asyncio.fixture
def patch_stream_db(test_engine, monkeypatch):
    """Point the stream generators' AsyncSessionLocal at the test engine."""
    maker = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(db_module, "AsyncSessionLocal", maker)
    return maker


async def _drive_stream(gen, do_post, *, settle=0.8, timeout=10.0):
    """Consume ``gen`` in the background until it yields an ``event: message``.

    Lets the generator subscribe (``settle``s), fires ``do_post`` (which posts a
    message), and returns the collected SSE chunks. Cancels the generator on the
    way out so its pubsub is closed.
    """
    collected: list[str] = []

    async def _consume():
        async for chunk in gen:
            collected.append(chunk)
            if "event: message" in chunk:
                return

    task = asyncio.create_task(_consume())
    try:
        await asyncio.sleep(settle)
        await do_post()
        await asyncio.wait_for(task, timeout=timeout)
    finally:
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    return collected


class TestChatStream:
    async def test_publish_wakes_stream(
        self, patch_stream_db, db_session, test_family, test_parent_user
    ):
        gen = FamilyChatService.stream_messages(test_family.id)

        async def _post():
            await FamilyChatService.post_message(
                db_session, test_family.id, test_parent_user.id, "hola pubsub"
            )

        chunks = await _drive_stream(gen, _post)
        assert any("hola pubsub" in c for c in chunks)

    async def test_fallback_delivers_when_publish_dropped(
        self, patch_stream_db, db_session, test_family, test_parent_user, monkeypatch
    ):
        # Simulate a dropped/never-sent publish, and shrink the fallback so the
        # DB re-read fires quickly.
        async def _noop_publish(*a, **k):
            return None

        monkeypatch.setattr(message_bus, "publish", _noop_publish)
        monkeypatch.setattr(family_chat_service, "FALLBACK_POLL_SECONDS", 0.5)

        gen = FamilyChatService.stream_messages(test_family.id)

        async def _post():
            await FamilyChatService.post_message(
                db_session, test_family.id, test_parent_user.id, "fallback msg"
            )

        chunks = await _drive_stream(gen, _post, timeout=8.0)
        assert any("fallback msg" in c for c in chunks)


class TestDMStream:
    async def test_publish_wakes_stream(
        self,
        patch_stream_db,
        db_session,
        test_family,
        test_parent_user,
        test_child_user,
    ):
        thread = await DMService.create_thread(
            db_session,
            test_family.id,
            test_parent_user.id,
            [test_child_user.id],
        )
        gen = DMService.stream_messages(
            thread.id, test_parent_user.id, test_family.id
        )

        async def _post():
            await DMService.post_message(
                db_session,
                thread.id,
                test_child_user.id,
                test_family.id,
                "dm pubsub",
            )

        chunks = await _drive_stream(gen, _post)
        assert any("dm pubsub" in c for c in chunks)
