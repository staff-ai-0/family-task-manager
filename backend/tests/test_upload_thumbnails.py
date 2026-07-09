"""Thumbnail generation + serving for uploaded proof / receipt-draft images.

Covers the LOW-severity performance work: at upload time a ~200px WebP thumb is
written alongside the original; list/approval views request it via ?size=thumb.
Requirements exercised here:
  - thumbnail is generated on upload and written next to the original
  - the thumb is served (WebP, immutable cache) through the authenticated route
  - it stays family-scoped (unauth → 401, other family → 404)
  - the full original is still served (no ?size)
  - a malformed image is handled gracefully: upload still succeeds, no thumb is
    written, and ?size=thumb transparently falls back to the full original
  - the receipt-draft image route honours ?size=thumb with the same fallback
"""
import io
import os
import uuid

import pytest
from httpx import AsyncClient

from app.api.routes.uploads import GIG_PROOFS_DIR
from app.core.thumbnails import make_webp_thumbnail, thumb_filename, THUMB_MAX_DIM
from app.services.budget.receipt_scanner_service import RECEIPT_UPLOADS_DIR


# ── helpers ──────────────────────────────────────────────────────────────

def _img_bytes(fmt: str = "PNG", color=(200, 120, 40), size=(640, 480)) -> bytes:
    """A real, decodable image (needs Pillow — same dep the feature uses)."""
    from PIL import Image

    im = Image.new("RGB", size, color)
    buf = io.BytesIO()
    im.save(buf, format=fmt)
    return buf.getvalue()


# A payload that PASSES magic-byte sniffing (JPEG SOI) but is NOT a real image,
# so Pillow can't decode it — the "malformed image" path.
_BROKEN_JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"garbage-not-an-image" + b"\x00" * 32


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _token(client: AsyncClient, email: str, password: str = "password123") -> str:
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def _register_claim(db_session, family_id, claimed_by, url: str):
    """Give a family ownership of an uploaded proof URL (so serving is allowed)."""
    from app.models.gig import GigOffering, GigClaim, GigClaimStatus

    offering = GigOffering(
        family_id=family_id, title="Wash car", points=10, created_by=claimed_by
    )
    db_session.add(offering)
    await db_session.flush()
    claim = GigClaim(
        gig_id=offering.id,
        family_id=family_id,
        claimed_by=claimed_by,
        status=GigClaimStatus.COMPLETED,
        proof_image_url=url,
    )
    db_session.add(claim)
    await db_session.commit()


# ── unit: the thumbnail util ─────────────────────────────────────────────

def test_make_webp_thumbnail_downsizes_real_image():
    out = make_webp_thumbnail(_img_bytes(size=(640, 480)))
    assert out is not None
    # WebP container magic.
    assert out[:4] == b"RIFF" and out[8:12] == b"WEBP"
    from PIL import Image

    with Image.open(io.BytesIO(out)) as im:
        assert max(im.size) <= THUMB_MAX_DIM
        # Aspect ratio preserved: 640x480 → 200x150.
        assert im.size == (200, 150)


def test_make_webp_thumbnail_never_upscales():
    out = make_webp_thumbnail(_img_bytes(size=(80, 60)))
    assert out is not None
    from PIL import Image

    with Image.open(io.BytesIO(out)) as im:
        assert im.size == (80, 60)


def test_make_webp_thumbnail_malformed_returns_none():
    assert make_webp_thumbnail(_BROKEN_JPEG) is None
    assert make_webp_thumbnail(b"") is None
    assert make_webp_thumbnail(b"not an image at all, just text") is None


def test_thumb_filename_maps_stem_to_webp():
    assert thumb_filename("abc123.jpg") == "abc123.thumb.webp"
    assert thumb_filename("abc123.png") == "abc123.thumb.webp"
    assert thumb_filename("de-ad-be-ef.webp") == "de-ad-be-ef.thumb.webp"


# ── e2e: gig/task proof upload → thumb → serve ───────────────────────────

@pytest.mark.asyncio
async def test_upload_writes_thumbnail_alongside_original(client, auth_headers):
    files = {"file": ("real.png", _img_bytes(fmt="PNG"), "image/png")}
    r = await client.post(
        "/api/task-assignments/proof-upload", files=files, headers=auth_headers
    )
    assert r.status_code == 200, r.text
    fname = r.json()["proof_image_url"].rsplit("/", 1)[-1]

    assert os.path.isfile(os.path.join(GIG_PROOFS_DIR, fname))
    thumb_path = os.path.join(GIG_PROOFS_DIR, thumb_filename(fname))
    assert os.path.isfile(thumb_path), "thumbnail not written next to original"
    with open(thumb_path, "rb") as fh:
        head = fh.read(12)
    assert head[:4] == b"RIFF" and head[8:12] == b"WEBP"


@pytest.mark.asyncio
async def test_thumb_and_original_both_served(
    client, db_session, auth_headers, test_parent_user, test_child_user
):
    files = {"file": ("real.jpg", _img_bytes(fmt="JPEG"), "image/jpeg")}
    r = await client.post(
        "/api/task-assignments/proof-upload", files=files, headers=auth_headers
    )
    url = r.json()["proof_image_url"]
    await _register_claim(
        db_session, test_parent_user.family_id, test_child_user.id, url
    )
    token = await _token(client, "parent@test.com")

    # Thumbnail: WebP + immutable cache.
    rt = await client.get(f"{url}?size=thumb", headers=_auth(token))
    assert rt.status_code == 200, rt.text
    assert rt.headers["content-type"] == "image/webp"
    assert "immutable" in rt.headers.get("cache-control", "")
    assert rt.content[:4] == b"RIFF" and rt.content[8:12] == b"WEBP"

    # Full original still served (JPEG bytes).
    rf = await client.get(url, headers=_auth(token))
    assert rf.status_code == 200, rf.text
    assert rf.content[:3] == b"\xff\xd8\xff"


@pytest.mark.asyncio
async def test_thumb_requires_auth(client, db_session, test_parent_user, test_child_user):
    fname = f"{uuid.uuid4().hex}.jpg"
    url = f"/uploads/gig-proofs/{fname}"
    await _register_claim(db_session, test_parent_user.family_id, test_child_user.id, url)
    os.makedirs(GIG_PROOFS_DIR, exist_ok=True)
    with open(os.path.join(GIG_PROOFS_DIR, thumb_filename(fname)), "wb") as fh:
        fh.write(make_webp_thumbnail(_img_bytes()) or b"")

    r = await client.get(f"{url}?size=thumb")  # no Authorization header
    assert r.status_code == 401, r.text


@pytest.mark.asyncio
async def test_thumb_blocked_cross_family(
    client, db_session, test_parent_user, test_child_user
):
    """A parent in another family must not read this family's thumbnail."""
    from app.models.family import Family
    from app.models.user import User, UserRole
    from app.core.security import get_password_hash

    fname = f"{uuid.uuid4().hex}.jpg"
    url = f"/uploads/gig-proofs/{fname}"
    await _register_claim(db_session, test_parent_user.family_id, test_child_user.id, url)
    os.makedirs(GIG_PROOFS_DIR, exist_ok=True)
    with open(os.path.join(GIG_PROOFS_DIR, thumb_filename(fname)), "wb") as fh:
        fh.write(make_webp_thumbnail(_img_bytes()) or b"")

    other_fam = Family(name="Outsider Family")
    db_session.add(other_fam)
    await db_session.flush()
    outsider = User(
        email="outsider-thumb@test.com",
        password_hash=get_password_hash("password123"),
        name="Outsider",
        role=UserRole.PARENT,
        family_id=other_fam.id,
        email_verified=True,
    )
    db_session.add(outsider)
    await db_session.commit()

    token = await _token(client, "outsider-thumb@test.com")
    r = await client.get(f"{url}?size=thumb", headers=_auth(token))
    assert r.status_code == 404, r.text  # no existence leak


@pytest.mark.asyncio
async def test_malformed_upload_has_no_thumb_and_falls_back(
    client, db_session, auth_headers, test_parent_user, test_child_user
):
    """A magic-byte-valid but undecodable image: upload succeeds, no thumb is
    written, and ?size=thumb transparently serves the full original."""
    files = {"file": ("broken.jpg", _BROKEN_JPEG, "image/jpeg")}
    r = await client.post(
        "/api/task-assignments/proof-upload", files=files, headers=auth_headers
    )
    assert r.status_code == 200, r.text  # graceful — upload not blocked
    url = r.json()["proof_image_url"]
    fname = url.rsplit("/", 1)[-1]

    # No thumbnail was produced for the broken image.
    assert not os.path.isfile(os.path.join(GIG_PROOFS_DIR, thumb_filename(fname)))

    await _register_claim(
        db_session, test_parent_user.family_id, test_child_user.id, url
    )
    token = await _token(client, "parent@test.com")

    # ?size=thumb falls back to the full original rather than 404-ing.
    rt = await client.get(f"{url}?size=thumb", headers=_auth(token))
    assert rt.status_code == 200, rt.text
    assert rt.content == _BROKEN_JPEG


# ── e2e: receipt-draft image route honours ?size=thumb ───────────────────

async def _make_receipt_draft(db_session, family_id):
    from app.models.budget import BudgetAccount, BudgetReceiptDraft

    acct = BudgetAccount(family_id=family_id, name="Cash", type="checking")
    db_session.add(acct)
    await db_session.flush()
    draft = BudgetReceiptDraft(
        family_id=family_id,
        account_id=acct.id,
        scanned_data={"payee_name": "Store", "amount": "10.00"},
        confidence=0.1,
        status="pending",
        image_url="placeholder",
    )
    db_session.add(draft)
    await db_session.commit()
    await db_session.refresh(draft)
    return draft


@pytest.mark.asyncio
async def test_receipt_draft_thumb_served_with_fallback(
    client, db_session, test_parent_user
):
    draft = await _make_receipt_draft(db_session, test_parent_user.family_id)
    os.makedirs(RECEIPT_UPLOADS_DIR, exist_ok=True)
    jpg = _img_bytes(fmt="JPEG")
    with open(os.path.join(RECEIPT_UPLOADS_DIR, f"{draft.id}.jpg"), "wb") as fh:
        fh.write(jpg)
    with open(
        os.path.join(RECEIPT_UPLOADS_DIR, thumb_filename(f"{draft.id}.jpg")), "wb"
    ) as fh:
        fh.write(make_webp_thumbnail(jpg) or b"")

    token = await _token(client, "parent@test.com")
    base = f"/api/budget/receipt-drafts/{draft.id}/image"

    rt = await client.get(f"{base}?size=thumb", headers=_auth(token))
    assert rt.status_code == 200, rt.text
    assert rt.headers["content-type"] == "image/webp"

    rf = await client.get(base, headers=_auth(token))
    assert rf.status_code == 200, rf.text
    assert rf.headers["content-type"] == "image/jpeg"

    # Remove the thumb → ?size=thumb falls back to the full JPEG.
    os.remove(os.path.join(RECEIPT_UPLOADS_DIR, thumb_filename(f"{draft.id}.jpg")))
    rfb = await client.get(f"{base}?size=thumb", headers=_auth(token))
    assert rfb.status_code == 200, rfb.text
    assert rfb.headers["content-type"] == "image/jpeg"
