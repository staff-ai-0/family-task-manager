"""Shared upload hardening: magic-byte sniffing + size-capped reads.

Client-supplied Content-Type is attacker-controlled, so the real type is
sniffed from the file's leading bytes. Reads are streamed with a hard byte
cap so a large authenticated upload cannot exhaust a worker's memory.

Also home to the allow-list for proof-image *paths* coming back in a request
body (``clean_proof_url``) — the read side of the same trust boundary.
"""
import re
from typing import Optional, Set

from fastapi import UploadFile, HTTPException

from app.core.exceptions import ValidationException

# Size limits (bytes).
MB = 1024 * 1024
MAX_IMPORT_BYTES = 10 * MB        # CSV / OFX / QIF / CAMT bank files
MAX_RECEIPT_BYTES = 15 * MB       # receipt photos / scanned PDFs
MAX_PROOF_BYTES = 5 * MB          # gig proof images
MAX_BACKUP_BYTES = 25 * MB        # full budget export ZIP (JSON-in-ZIP, small)

_CHUNK = 64 * 1024

# Exactly what POST /api/task-assignments/proof-upload returns:
# /uploads/gig-proofs/<uuid4-hex>.<jpg|png|webp>. Matched with fullmatch, so
# no traversal, no scheme, no host, no query.
PROOF_URL_RE = re.compile(r"/uploads/gig-proofs/[0-9a-f]{32}\.(?:jpg|png|webp)")


def clean_proof_url(proof_image_url: Optional[str]) -> Optional[str]:
    """Accept only a proof path this app issued; return it trimmed.

    proof_image_url is rendered straight into an <img src> in the PARENT's
    approval queue (/parent/approvals), so an arbitrary client-supplied value
    is a stored injection aimed at the grader — an off-site fetch from their
    browser at best, a javascript:/data: payload at worst. THE single gate:
    every path that persists a proof image path must go through here,
    above all the KID-facing completion paths, where the submitter is the
    untrusted party.

    Blank normalises to None rather than raising. That is a deliberate
    convenience, NOT something a caller depends on: no client in this repo
    sends "". The dashboard's completion form does post an empty hidden
    proof_image_url, but its Astro proxy (pages/api/assignments/complete.ts)
    already collapses it to null before the backend sees it, and every other
    caller either omits the key or sends null.

    It is kept because "" and None mean the same thing here — "no photo" — and
    that is not an error condition: the callers that REQUIRE a photo check for
    themselves, after this, with their own message. Rejecting "" would buy no
    security (a blank string is not a path and can never reach an <img src>)
    while turning a no-op into a 422 for any form-encoded or native client
    outside this repo that posts an empty field. The allow-list below is what
    does the actual work.
    """
    if proof_image_url is None:
        return None
    cleaned = proof_image_url.strip()
    if not cleaned:
        return None
    if not PROOF_URL_RE.fullmatch(cleaned):
        raise ValidationException(
            "proof_image_url must be a path returned by "
            "POST /api/task-assignments/proof-upload"
        )
    return cleaned


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
