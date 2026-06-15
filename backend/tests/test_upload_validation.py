"""Upload hardening: magic-byte sniffing + size-capped reads.

Client-supplied Content-Type is not trusted; the real type is sniffed from the
leading bytes. Reads are capped so a large authed upload can't exhaust a worker.
"""
import io

import pytest
from fastapi import UploadFile, HTTPException

from app.core.upload_validation import (
    sniff_mime,
    read_upload_capped,
    assert_allowed_type,
)

JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 32
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 16
GIF = b"GIF89a" + b"\x00" * 32
PDF = b"%PDF-1.7\n" + b"\x00" * 32
TEXT = b"id,amount,payee\n1,100,Store\n"


@pytest.mark.parametrize(
    "data,expected",
    [
        (JPEG, "image/jpeg"),
        (PNG, "image/png"),
        (WEBP, "image/webp"),
        (GIF, "image/gif"),
        (PDF, "application/pdf"),
        (TEXT, None),
        (b"", None),
        (b"\x00\x01\x02\x03not-an-image", None),
    ],
)
def test_sniff_mime(data, expected):
    assert sniff_mime(data) == expected


def test_assert_allowed_type_accepts_real_image():
    # Must not raise — JPEG bytes are in the allow-list.
    assert_allowed_type(JPEG, {"image/jpeg", "image/png"})


def test_assert_allowed_type_rejects_spoofed_content_type():
    # Text payload masquerading as a JPEG upload must be rejected (415).
    with pytest.raises(HTTPException) as exc:
        assert_allowed_type(TEXT, {"image/jpeg", "image/png"})
    assert exc.value.status_code == 415


def _upload(data: bytes) -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename="f.bin")


@pytest.mark.asyncio
async def test_read_upload_capped_under_limit():
    up = _upload(b"x" * 1000)
    data = await read_upload_capped(up, max_bytes=2000)
    assert data == b"x" * 1000


@pytest.mark.asyncio
async def test_read_upload_capped_over_limit_raises_413():
    up = _upload(b"x" * 5000)
    with pytest.raises(HTTPException) as exc:
        await read_upload_capped(up, max_bytes=2000)
    assert exc.value.status_code == 413
