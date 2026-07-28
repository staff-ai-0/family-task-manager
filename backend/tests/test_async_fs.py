"""Blocking disk I/O stays off the event loop.

Receipt and proof images are user-uploaded phone photos — megabytes each. Read
or written with a bare `open()` inside an `async def`, they hold the single
event-loop thread for the whole transfer and every other in-flight request
stalls behind them. `app/core/async_fs.py` is the one sanctioned way to touch
the uploads volume from async code; ruff's ASYNC rules block the alternatives.

Covers the helpers' semantics plus the property that actually matters (the work
runs on a worker thread, not the loop), and the one call site whose control flow
changed shape: `task_proof_validator._load_image_bytes`.
"""
import os
import threading

import pytest

from app.core import async_fs


# ── write_bytes ──────────────────────────────────────────────────────────

async def test_write_bytes_creates_missing_parents(tmp_path):
    target = tmp_path / "gig-proofs" / "abc123.jpg"

    await async_fs.write_bytes(str(target), b"\xff\xd8image-bytes")

    assert target.read_bytes() == b"\xff\xd8image-bytes"


async def test_write_bytes_overwrites_existing(tmp_path):
    target = tmp_path / "abc123.jpg"
    target.write_bytes(b"stale")

    await async_fs.write_bytes(str(target), b"fresh")

    assert target.read_bytes() == b"fresh"


async def test_write_bytes_accepts_a_bare_filename(tmp_path, monkeypatch):
    # os.path.dirname("f.jpg") is "" — makedirs must be skipped, not called
    # with an empty path (which would raise).
    monkeypatch.chdir(tmp_path)

    await async_fs.write_bytes("f.jpg", b"ok")

    assert (tmp_path / "f.jpg").read_bytes() == b"ok"


# ── read_bytes_or_none ───────────────────────────────────────────────────

async def test_read_bytes_or_none_returns_contents(tmp_path):
    src = tmp_path / "proof.png"
    src.write_bytes(b"\x89PNG\r\n\x1a\n")

    assert await async_fs.read_bytes_or_none(str(src)) == b"\x89PNG\r\n\x1a\n"


async def test_read_bytes_or_none_returns_none_when_absent(tmp_path):
    assert await async_fs.read_bytes_or_none(str(tmp_path / "gone.png")) is None


async def test_read_bytes_or_none_propagates_non_absence_errors(tmp_path):
    # Only "the file isn't there" is None. A path that exists but can't be read
    # is a real fault and must surface, not masquerade as a missing upload.
    a_directory = tmp_path / "subdir"
    a_directory.mkdir()

    with pytest.raises(OSError):
        await async_fs.read_bytes_or_none(str(a_directory))


# ── read_text ────────────────────────────────────────────────────────────

async def test_read_text_decodes_utf8(tmp_path):
    src = tmp_path / "invitation.html"
    src.write_text("<p>¡Te han invitado!</p>", encoding="utf-8")

    assert await async_fs.read_text(str(src)) == "<p>¡Te han invitado!</p>"


async def test_read_text_raises_file_not_found(tmp_path):
    # email_service catches exactly this to fall back to its inline template.
    with pytest.raises(FileNotFoundError):
        await async_fs.read_text(str(tmp_path / "missing.html"))


# ── exists / is_file ─────────────────────────────────────────────────────

async def test_exists_and_is_file_on_a_file(tmp_path):
    src = tmp_path / "receipt.jpg"
    src.write_bytes(b"x")

    assert await async_fs.exists(str(src)) is True
    assert await async_fs.is_file(str(src)) is True


async def test_exists_and_is_file_disagree_on_a_directory(tmp_path):
    a_directory = tmp_path / "subdir"
    a_directory.mkdir()

    assert await async_fs.exists(str(a_directory)) is True
    assert await async_fs.is_file(str(a_directory)) is False


async def test_exists_and_is_file_on_a_missing_path(tmp_path):
    assert await async_fs.exists(str(tmp_path / "gone")) is False
    assert await async_fs.is_file(str(tmp_path / "gone")) is False


# ── the actual point: none of it runs on the event loop ──────────────────

async def test_write_bytes_runs_on_a_worker_thread(tmp_path, monkeypatch):
    loop_thread = threading.get_ident()
    target = tmp_path / "nested" / "big.jpg"
    seen: list[int] = []
    real_makedirs = os.makedirs

    def spy(path, *args, **kwargs):
        if str(path) == str(target.parent):
            seen.append(threading.get_ident())
        return real_makedirs(path, *args, **kwargs)

    monkeypatch.setattr(os, "makedirs", spy)
    await async_fs.write_bytes(str(target), b"payload")

    assert seen, "write_bytes never created the parent directory"
    assert loop_thread not in seen


async def test_read_bytes_or_none_runs_on_a_worker_thread(tmp_path, monkeypatch):
    loop_thread = threading.get_ident()
    src = tmp_path / "proof.jpg"
    src.write_bytes(b"payload")
    seen: list[int] = []
    real_exists = os.path.exists

    def spy(path):
        if str(path) == str(src):
            seen.append(threading.get_ident())
        return real_exists(path)

    monkeypatch.setattr(os.path, "exists", spy)
    assert await async_fs.read_bytes_or_none(str(src)) == b"payload"

    assert seen, "read_bytes_or_none never stat'd the target"
    assert loop_thread not in seen


# ── call site: task_proof_validator._load_image_bytes ─────────────────────

class _StubResponse:
    def __init__(self, content: bytes, content_type: str):
        self.content = content
        self.headers = {"content-type": content_type}

    def raise_for_status(self) -> None:
        pass


class _StubAsyncClient:
    """Records the URL a remote fetch was attempted against."""

    def __init__(self, calls: list, **_kwargs):
        self._calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def get(self, url: str):
        self._calls.append(url)
        return _StubResponse(b"remote-bytes", "image/png; charset=binary")


@pytest.mark.parametrize(
    "suffix,expected_type",
    [
        ("jpg", "image/jpeg"),
        ("jpeg", "image/jpeg"),
        ("png", "image/png"),
        ("webp", "image/webp"),
        ("gif", "image/gif"),
        ("bin", "image/jpeg"),  # unknown suffix falls back to JPEG
    ],
)
async def test_load_image_bytes_reads_the_local_upload(
    tmp_path, monkeypatch, suffix, expected_type
):
    from app.services import task_proof_validator as tpv

    src = tmp_path / f"proof.{suffix}"
    src.write_bytes(b"local-bytes")
    monkeypatch.setattr(tpv, "_strip_local_prefix", lambda _url: str(src))

    data, media_type = await tpv._load_image_bytes("/uploads/gig-proofs/proof.jpg")

    assert data == b"local-bytes"
    assert media_type == expected_type


async def test_load_image_bytes_falls_back_to_remote_when_local_is_absent(
    tmp_path, monkeypatch
):
    from app.services import task_proof_validator as tpv

    missing = str(tmp_path / "not-written.jpg")
    monkeypatch.setattr(tpv, "_strip_local_prefix", lambda _url: missing)
    calls: list = []
    monkeypatch.setattr(
        tpv.httpx, "AsyncClient", lambda **kw: _StubAsyncClient(calls, **kw)
    )

    data, media_type = await tpv._load_image_bytes("https://cdn.example/p.png")

    assert data == b"remote-bytes"
    assert media_type == "image/png"
    assert calls == ["https://cdn.example/p.png"]


async def test_load_image_bytes_fetches_remotely_for_non_upload_urls(monkeypatch):
    from app.services import task_proof_validator as tpv

    calls: list = []
    monkeypatch.setattr(
        tpv.httpx, "AsyncClient", lambda **kw: _StubAsyncClient(calls, **kw)
    )

    data, _media_type = await tpv._load_image_bytes("https://cdn.example/p.png")

    assert data == b"remote-bytes"
    assert calls == ["https://cdn.example/p.png"]
