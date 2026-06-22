"""End-to-end upload hardening at the HTTP layer: magic-byte sniffing on the
gig proof upload and a size cap on CSV import."""
from uuid import uuid4

import pytest

REAL_JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 64


@pytest.mark.asyncio
async def test_proof_upload_rejects_spoofed_content_type(client, auth_headers):
    """A text payload that merely *claims* image/jpeg must be rejected (415)."""
    files = {"file": ("fake.jpg", b"this is plain text, not an image", "image/jpeg")}
    resp = await client.post(
        "/api/task-assignments/proof-upload", files=files, headers=auth_headers
    )
    assert resp.status_code == 415, resp.text


@pytest.mark.asyncio
async def test_proof_upload_accepts_real_jpeg(client, auth_headers):
    files = {"file": ("real.jpg", REAL_JPEG, "image/jpeg")}
    resp = await client.post(
        "/api/task-assignments/proof-upload", files=files, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["proof_image_url"].startswith("/uploads/gig-proofs/")


@pytest.mark.asyncio
async def test_csv_import_rejects_oversized_file(client, auth_headers):
    """An over-cap CSV must be refused before the whole body is buffered.

    The size check fires before account validation, so a placeholder
    account_id is fine — the response must cite the size limit, not 'account
    not found' (which is what an unguarded read would surface)."""
    oversized = b"x" * (10 * 1024 * 1024 + 1)
    files = {"file": ("big.csv", oversized, "text/csv")}
    resp = await client.post(
        f"/api/budget/transactions/import/csv?account_id={uuid4()}",
        files=files,
        headers=auth_headers,
    )
    body = resp.json()
    assert body["success"] is False, body
    err = str(body.get("error", "")).lower()
    assert "mb" in err or "too large" in err, body


@pytest.mark.asyncio
async def test_import_backup_rejects_oversized_file(client, auth_headers):
    """An over-cap backup ZIP must be refused before the body is buffered and
    before any destructive import/clear runs."""
    oversized = b"x" * (25 * 1024 * 1024 + 1)
    files = {"file": ("big.zip", oversized, "application/zip")}
    resp = await client.post(
        "/api/budget/import-backup", files=files, headers=auth_headers
    )
    assert resp.status_code == 413, resp.text
    assert "too large" in resp.json()["detail"].lower()
