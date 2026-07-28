"""Blocking filesystem calls, hopped off the event loop.

Every path that reaches here touches the uploads volume — receipt and proof
photos a phone camera routinely produces at several megabytes. A plain
``open()`` inside an ``async def`` holds the single event-loop thread for the
whole read/write, so one upload freezes every other in-flight request. The
``os.path`` predicates are individually cheap, but they sit on the same
image-serving routes and are the one call left that could block if the uploads
volume is ever anything but local disk.

Work runs through ``run_in_threadpool`` — anyio's bounded worker pool, the same
one Starlette uses for sync endpoints — rather than ``asyncio.to_thread``, so
filesystem work shares the app's existing thread budget instead of the default
executor's.

Ruff's ASYNC rules (see ``backend/ruff.toml``) keep new blocking calls from
sneaking back into async code; route them through here instead.
"""
from __future__ import annotations

import os

from starlette.concurrency import run_in_threadpool


# ── blocking primitives (call only from a worker thread) ─────────────────

def _read_bytes_or_none(path: str) -> bytes | None:
    """Existence check and read in ONE hop — two awaits would double the
    round-trip and leave a window where the file vanishes in between."""
    if not os.path.exists(path):
        return None
    with open(path, "rb") as fh:
        return fh.read()


def _read_text(path: str, encoding: str) -> str:
    with open(path, encoding=encoding) as fh:
        return fh.read()


def _write_bytes(path: str, data: bytes) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)


# ── async wrappers ───────────────────────────────────────────────────────

async def read_bytes_or_none(path: str) -> bytes | None:
    """File contents, or ``None`` when the file does not exist.

    Read errors other than absence (permissions, I/O) still raise.
    """
    return await run_in_threadpool(_read_bytes_or_none, path)


async def read_text(path: str, *, encoding: str = "utf-8") -> str:
    """File contents as text. Raises ``FileNotFoundError`` when absent."""
    return await run_in_threadpool(_read_text, path, encoding)


async def write_bytes(path: str, data: bytes) -> None:
    """Write ``data`` to ``path``, creating parent directories as needed."""
    await run_in_threadpool(_write_bytes, path, data)


async def exists(path: str) -> bool:
    return await run_in_threadpool(os.path.exists, path)


async def is_file(path: str) -> bool:
    return await run_in_threadpool(os.path.isfile, path)
