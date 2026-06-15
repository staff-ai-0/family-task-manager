"""Shared upload hardening: magic-byte sniffing + size-capped reads.

Client-supplied Content-Type is attacker-controlled, so the real type is
sniffed from the file's leading bytes. Reads are streamed with a hard byte
cap so a large authenticated upload cannot exhaust a worker's memory.
"""
from typing import Optional, Set

from fastapi import UploadFile, HTTPException

# Size limits (bytes).
MB = 1024 * 1024
MAX_IMPORT_BYTES = 10 * MB        # CSV / OFX / QIF / CAMT bank files
MAX_RECEIPT_BYTES = 15 * MB       # receipt photos / scanned PDFs
MAX_PROOF_BYTES = 5 * MB          # gig proof images

_CHUNK = 64 * 1024


def sniff_mime(data: bytes) -> Optional[str]:
    """Return the MIME type implied by the leading magic bytes, or None.

    Recognizes the formats this app accepts for upload (images + PDF). Anything
    else returns None so callers can reject it regardless of the claimed type.
    """
    if len(data) < 4:
        return None
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"%PDF":
        return "application/pdf"
    return None


def assert_allowed_type(data: bytes, allowed: Set[str]) -> str:
    """Sniff the real type and raise 415 unless it is in ``allowed``.

    Returns the detected MIME type on success.
    """
    detected = sniff_mime(data)
    if detected not in allowed:
        raise HTTPException(
            status_code=415,
            detail=(
                "Unsupported or unrecognized file content. "
                f"Allowed: {', '.join(sorted(allowed))}."
            ),
        )
    return detected


async def read_upload_capped(file: UploadFile, max_bytes: int) -> bytes:
    """Read an UploadFile in chunks, aborting with 413 if it exceeds max_bytes.

    Avoids loading an unbounded body into memory via a single ``file.read()``.
    """
    chunks = []
    total = 0
    while True:
        chunk = await file.read(_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File too large (max {max_bytes // MB} MB).",
            )
        chunks.append(chunk)
    return b"".join(chunks)
