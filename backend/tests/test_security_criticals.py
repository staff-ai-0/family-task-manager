"""Regression tests for the Track-A security criticals (audit 2026-06-04).

A1 — /api/auth/register was an unauthenticated cross-tenant privilege escalation:
     it trusted a client-supplied family_id + role, so anyone could mint a PARENT
     in ANY family. Registration of members must require an authenticated PARENT,
     and the new member's family must come from the caller's JWT (never the body).

A2 — the backend mounted /uploads as public StaticFiles (no auth), so every
     gig-proof / receipt image was readable by anyone over the public tunnel.
     Serving must require auth AND be scoped to the caller's family.
"""
import os
import uuid

import pytest
from httpx import AsyncClient


async def _token(client: AsyncClient, email: str, password: str = "password123") -> str:
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ─────────────────────────── A1: register access control ───────────────────────────

class TestRegisterAccessControl:
    @pytest.mark.asyncio
    async def test_unauthenticated_register_is_rejected(self, client: AsyncClient, test_family):
        """The core hole: no token at all must NOT create a user (was 201)."""
        r = await client.post(
            "/api/auth/register",
            json={
                "email": "intruder@evil.com",
                "name": "Intruder",
                "password": "password123",
                "role": "parent",
                "family_id": str(test_family.id),
            },
        )
        assert r.status_code == 401, r.text

    @pytest.mark.asyncio
    async def test_child_cannot_register_members(
        self, client: AsyncClient, test_child_user, test_family
    ):
        token = await _token(client, "child@test.com")
        r = await client.post(
            "/api/auth/register",
            headers=_auth(token),
            json={
                "email": "x@test.com",
                "name": "X",
                "password": "password123",
                "role": "child",
                "family_id": str(test_family.id),
            },
        )
        assert r.status_code == 403, r.text

    @pytest.mark.asyncio
    async def test_parent_register_uses_caller_family_not_body(
        self, client: AsyncClient, db_session, test_parent_user
    ):
        """A parent cannot plant a user into another family by passing its id."""
        from app.models.family import Family

        other = Family(name="Victim Family")
        db_session.add(other)
        await db_session.commit()
        await db_session.refresh(other)

        token = await _token(client, "parent@test.com")
        r = await client.post(
            "/api/auth/register",
            headers=_auth(token),
            json={
                "email": "newkid@test.com",
                "name": "New Kid",
                "password": "password123",
                "role": "child",
                "family_id": str(other.id),  # malicious: a different family
            },
        )
        assert r.status_code == 201, r.text
        # Must land in the CALLER's family, not the body-supplied one.
        assert r.json()["family_id"] == str(test_parent_user.family_id)
        assert r.json()["family_id"] != str(other.id)

    @pytest.mark.asyncio
    async def test_parent_can_add_member_to_own_family(
        self, client: AsyncClient, test_parent_user, test_family
    ):
        token = await _token(client, "parent@test.com")
        r = await client.post(
            "/api/auth/register",
            headers=_auth(token),
            json={
                "email": "sibling@test.com",
                "name": "Sibling",
                "password": "password123",
                "role": "teen",
                "family_id": str(test_family.id),
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["role"] == "teen"
        assert r.json()["family_id"] == str(test_family.id)


# ─────────────────────────── A2: uploads auth + family scope ───────────────────────────

UPLOAD_SUBDIR = "/app/uploads/gig-proofs"


async def _make_claim_with_proof(db_session, family_id, claimed_by, fname: str):
    """Create a gig offering + claim referencing a proof file, and write the file."""
    from app.models.gig import GigOffering, GigClaim, GigClaimStatus

    offering = GigOffering(family_id=family_id, title="Wash car", points=10, created_by=claimed_by)
    db_session.add(offering)
    await db_session.flush()
    claim = GigClaim(
        gig_id=offering.id,
        family_id=family_id,
        claimed_by=claimed_by,
        status=GigClaimStatus.COMPLETED,
        proof_image_url=f"/uploads/gig-proofs/{fname}",
    )
    db_session.add(claim)
    await db_session.commit()
    os.makedirs(UPLOAD_SUBDIR, exist_ok=True)
    with open(os.path.join(UPLOAD_SUBDIR, fname), "wb") as fh:
        fh.write(b"\xff\xd8\xffPROOFBYTES")  # fake jpeg
    return fname


class TestUploadsAuth:
    @pytest.mark.asyncio
    async def test_uploads_require_authentication(self, client: AsyncClient):
        """No public StaticFiles mount: unauthenticated fetch must be 401, not 200/404-static."""
        r = await client.get("/uploads/gig-proofs/whatever.jpg")
        assert r.status_code == 401, r.text

    @pytest.mark.asyncio
    async def test_uploads_serves_own_family_proof(
        self, client: AsyncClient, db_session, test_parent_user, test_child_user
    ):
        fname = f"{uuid.uuid4().hex}.jpg"
        await _make_claim_with_proof(
            db_session, test_parent_user.family_id, test_child_user.id, fname
        )
        token = await _token(client, "parent@test.com")
        r = await client.get(f"/uploads/gig-proofs/{fname}", headers=_auth(token))
        assert r.status_code == 200, r.text
        assert r.content == b"\xff\xd8\xffPROOFBYTES"

    @pytest.mark.asyncio
    async def test_uploads_blocks_other_family_proof(
        self, client: AsyncClient, db_session, test_parent_user, test_child_user
    ):
        """A user from another family must not read this family's proof image."""
        from app.models.family import Family
        from app.models.user import User, UserRole
        from app.core.security import get_password_hash

        # File belongs to test_parent_user's family.
        fname = f"{uuid.uuid4().hex}.jpg"
        await _make_claim_with_proof(
            db_session, test_parent_user.family_id, test_child_user.id, fname
        )

        # Outsider parent in a different family.
        other_fam = Family(name="Outsider Family")
        db_session.add(other_fam)
        await db_session.flush()
        outsider = User(
            email="outsider@test.com",
            password_hash=get_password_hash("password123"),
            name="Outsider",
            role=UserRole.PARENT,
            family_id=other_fam.id,
            email_verified=True,
        )
        db_session.add(outsider)
        await db_session.commit()

        token = await _token(client, "outsider@test.com")
        r = await client.get(f"/uploads/gig-proofs/{fname}", headers=_auth(token))
        assert r.status_code == 404, r.text  # not found / not yours — no existence leak

    @pytest.mark.asyncio
    async def test_uploads_rejects_path_traversal(
        self, client: AsyncClient, test_parent_user
    ):
        token = await _token(client, "parent@test.com")
        r = await client.get("/uploads/gig-proofs/..%2f..%2f..%2fetc%2fpasswd", headers=_auth(token))
        assert r.status_code in (400, 404), r.text


# ─────────────────────────── A3: LLM call must not block the loop ───────────────────────────

def _mock_completion(content: str):
    from unittest.mock import MagicMock

    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    comp = MagicMock()
    comp.choices = [choice]
    return comp


class TestReceiptScannerResilience:
    @pytest.mark.asyncio
    async def test_scan_receipt_sets_finite_timeout(self):
        """A hung LiteLLM/vision provider must not block the event loop forever:
        the OpenAI client must be constructed with a finite timeout (A3)."""
        from unittest.mock import patch, MagicMock
        from app.services.budget import receipt_scanner_service as svc

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_completion(
            '{"merchant": "Store", "total": 9.99, "currency": "MXN", '
            '"date": null, "line_items": [], "confidence": 0.95}'
        )
        with patch.object(svc, "settings") as mock_settings:
            mock_settings.LITELLM_API_KEY = "sk-fake"
            mock_settings.LITELLM_API_BASE = "http://proxy:4000"
            with patch.object(svc, "OpenAI") as mock_openai:
                mock_openai.return_value = mock_client
                try:
                    await svc.scan_receipt(b"fakebytes", "image/jpeg")
                except Exception:
                    pass  # downstream parsing/validation is not under test here
                mock_openai.assert_called_once()
                _, kwargs = mock_openai.call_args
                assert kwargs.get("timeout") is not None, (
                    "OpenAI client created without a timeout — a hung provider "
                    "would block the event loop"
                )
