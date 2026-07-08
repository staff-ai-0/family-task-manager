"""Consent capture + join-code parental approval (2026-07-07 compliance).

Covers:
- Family-create registration requires accept_terms and stores the consent
  timestamp + policy version.
- Join-by-family-code self-signups start PENDING: no tokens issued, parents
  notified in-app, login blocked (403) until a parent approves.
- Parent approve -> member can log in; reject -> account deleted.
- Approve/reject are parent-only and family-scoped (cross-family 403).
- Google OAuth signups obey the SAME gates: join_code/family_id signups are
  capped at CHILD/TEEN + pending with no tokens + parents notified, and
  new-family OAuth signups require accept_terms (consent recorded).
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.family import Family, generate_join_code
from app.models.notification import Notification
from app.models.user import (
    APPROVAL_APPROVED,
    APPROVAL_PENDING,
    CONSENT_POLICY_VERSION,
    User,
    UserRole,
)


async def _join_code_for(db_session, family) -> str:
    fam = (await db_session.execute(
        select(Family).where(Family.id == family.id)
    )).scalar_one()
    if not fam.join_code:
        fam.join_code = generate_join_code()
        await db_session.commit()
        await db_session.refresh(fam)
    return fam.join_code


async def _register_join(client: AsyncClient, code: str, *, email="pending-kid@test.com",
                         name="Pending Kid", role=None, birthdate=None):
    payload = {
        "email": email,
        "name": name,
        "password": "password123",
        "family_code": code,
        "accept_terms": True,
        "preferred_lang": "es",
    }
    if role:
        payload["role"] = role
    if birthdate:
        payload["birthdate"] = birthdate
    return await client.post("/api/auth/register-family", json=payload)


async def _parent_token(client: AsyncClient) -> str:
    r = await client.post(
        "/api/auth/login",
        json={"email": "parent@test.com", "password": "password123"},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


class TestConsentCapture:
    @pytest.mark.asyncio
    async def test_register_family_without_accept_terms_rejected(self, client):
        r = await client.post("/api/auth/register-family", json={
            "family_name": "No Consent Family",
            "name": "Founder",
            "email": "no-consent@test.com",
            "password": "password123",
        })
        assert r.status_code == 400, r.text

    @pytest.mark.asyncio
    async def test_register_family_with_accept_terms_false_rejected(self, client):
        r = await client.post("/api/auth/register-family", json={
            "family_name": "No Consent Family",
            "name": "Founder",
            "email": "no-consent-2@test.com",
            "password": "password123",
            "accept_terms": False,
        })
        assert r.status_code == 400, r.text

    @pytest.mark.asyncio
    async def test_register_family_stores_consent(self, client, db_session):
        r = await client.post("/api/auth/register-family", json={
            "family_name": "Consent Family",
            "name": "Founder",
            "email": "consenting@test.com",
            "password": "password123",
            "accept_terms": True,
        })
        assert r.status_code in (200, 201), r.text
        # Founder is approved immediately and gets tokens.
        body = r.json()
        assert body["access_token"]
        assert body["pending_approval"] is False

        user = (await db_session.execute(
            select(User).where(User.email == "consenting@test.com")
        )).scalar_one()
        assert user.consented_at is not None
        assert user.consent_policy_version == CONSENT_POLICY_VERSION
        assert user.approval_status == APPROVAL_APPROVED


class TestJoinCodePendingApproval:
    @pytest.mark.asyncio
    async def test_join_code_register_is_pending_no_token_parent_notified(
        self, client, db_session, test_family, test_parent_user
    ):
        code = await _join_code_for(db_session, test_family)
        r = await _register_join(client, code, birthdate="2015-04-02")
        assert r.status_code in (200, 201), r.text
        body = r.json()

        # (b) pending + NO tokens issued
        assert body["pending_approval"] is True
        assert body["access_token"] is None
        assert body["refresh_token"] is None
        assert body["message"]
        assert body["user"]["approval_status"] == APPROVAL_PENDING

        user = (await db_session.execute(
            select(User).where(User.email == "pending-kid@test.com")
        )).scalar_one()
        assert user.approval_status == APPROVAL_PENDING
        assert user.approved_at is None
        # (3) birthdate collected
        assert str(user.birthdate) == "2015-04-02"

        # (d) parent got an in-app notification
        notes = (await db_session.execute(
            select(Notification).where(
                Notification.user_id == test_parent_user.id,
                Notification.type == "member_pending_approval",
            )
        )).scalars().all()
        assert len(notes) == 1
        assert "Pending Kid" in (notes[0].body or "")
        assert notes[0].link == "/parent/members"

    @pytest.mark.asyncio
    async def test_login_blocked_while_pending(
        self, client, db_session, test_family, test_parent_user
    ):
        code = await _join_code_for(db_session, test_family)
        r = await _register_join(client, code)
        assert r.status_code in (200, 201)

        # (c) login while pending -> 403 with a pending-approval message
        r = await client.post("/api/auth/login", json={
            "email": "pending-kid@test.com", "password": "password123",
        })
        assert r.status_code == 403, r.text
        assert "pendiente de aprobación" in r.json()["message"].lower()

    @pytest.mark.asyncio
    async def test_parent_approve_allows_login(
        self, client, db_session, test_family, test_parent_user
    ):
        code = await _join_code_for(db_session, test_family)
        r = await _register_join(client, code)
        user_id = r.json()["user"]["id"]

        token = await _parent_token(client)
        r = await client.post(
            f"/api/users/{user_id}/approve",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["approval_status"] == APPROVAL_APPROVED

        user = (await db_session.execute(
            select(User).where(User.email == "pending-kid@test.com")
        )).scalar_one()
        await db_session.refresh(user)
        assert user.approval_status == APPROVAL_APPROVED
        assert user.approved_at is not None

        # Now login works
        r = await client.post("/api/auth/login", json={
            "email": "pending-kid@test.com", "password": "password123",
        })
        assert r.status_code == 200, r.text
        assert r.json()["access_token"]

    @pytest.mark.asyncio
    async def test_parent_reject_deletes_user(
        self, client, db_session, test_family, test_parent_user
    ):
        code = await _join_code_for(db_session, test_family)
        r = await _register_join(client, code)
        user_id = r.json()["user"]["id"]

        token = await _parent_token(client)
        r = await client.post(
            f"/api/users/{user_id}/reject",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 204, r.text

        gone = (await db_session.execute(
            select(User).where(User.email == "pending-kid@test.com")
        )).scalar_one_or_none()
        assert gone is None

        # Login now fails with invalid credentials (account gone)
        r = await client.post("/api/auth/login", json={
            "email": "pending-kid@test.com", "password": "password123",
        })
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_reject_removes_open_assignments_and_logs(
        self, client, db_session, test_family, test_parent_user, caplog
    ):
        """Rejecting a pending member must not let its open chores vanish
        silently through the assigned_to FK CASCADE: the route deletes the
        PENDING/OVERDUE rows explicitly and logs the count. (Pending members
        are excluded from the shuffle, so such rows are legacy data from
        before the approval gate.)"""
        import logging
        from datetime import date, timedelta
        from uuid import UUID

        from app.models.task_assignment import AssignmentStatus, TaskAssignment
        from app.models.task_template import TaskTemplate

        code = await _join_code_for(db_session, test_family)
        r = await _register_join(client, code, email="reject-chores@test.com")
        assert r.status_code in (200, 201), r.text
        pending_id = UUID(r.json()["user"]["id"])

        tmpl = TaskTemplate(
            title="Legacy chore",
            points=0,
            effort_level=1,
            interval_days=1,
            is_bonus=False,
            family_id=test_family.id,
            created_by=test_parent_user.id,
        )
        db_session.add(tmpl)
        await db_session.flush()
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        for a_status in (AssignmentStatus.PENDING, AssignmentStatus.OVERDUE):
            db_session.add(TaskAssignment(
                template_id=tmpl.id,
                assigned_to=pending_id,
                family_id=test_family.id,
                status=a_status,
                assigned_date=today,
                week_of=monday,
            ))
        await db_session.commit()

        token = await _parent_token(client)
        with caplog.at_level(logging.INFO, logger="app.api.routes.users"):
            r = await client.post(
                f"/api/users/{pending_id}/reject",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 204, r.text

        # Account gone
        gone = (await db_session.execute(
            select(User).where(User.email == "reject-chores@test.com")
        )).scalar_one_or_none()
        assert gone is None

        # No orphan assignment rows survive
        left = (await db_session.execute(
            select(TaskAssignment).where(TaskAssignment.assigned_to == pending_id)
        )).scalars().all()
        assert left == []

        # The cleanup is observable, not a silent cascade
        assert any(
            "removed 2 open assignment(s)" in rec.getMessage()
            for rec in caplog.records
        )

    @pytest.mark.asyncio
    async def test_child_cannot_approve(
        self, client, db_session, test_family, test_parent_user, test_child_user
    ):
        code = await _join_code_for(db_session, test_family)
        r = await _register_join(client, code)
        user_id = r.json()["user"]["id"]

        r = await client.post("/api/auth/login", json={
            "email": "child@test.com", "password": "password123",
        })
        child_token = r.json()["access_token"]

        r = await client.post(
            f"/api/users/{user_id}/approve",
            headers={"Authorization": f"Bearer {child_token}"},
        )
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_approve_non_pending_member_rejected(
        self, client, test_parent_user, test_child_user
    ):
        """Approve is not a generic toggle — approved members 400."""
        token = await _parent_token(client)
        r = await client.post(
            f"/api/users/{test_child_user.id}/approve",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_reject_non_pending_member_rejected(
        self, client, test_parent_user, test_child_user
    ):
        """Reject must not delete established (approved) members."""
        token = await _parent_token(client)
        r = await client.post(
            f"/api/users/{test_child_user.id}/reject",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_cross_family_parent_cannot_approve_or_reject(
        self, client, db_session, test_family, test_parent_user
    ):
        """TENANT ISOLATION: a parent of family B must get 403 on both
        approve and reject for a pending member of family A."""
        code = await _join_code_for(db_session, test_family)
        r = await _register_join(client, code)
        pending_id = r.json()["user"]["id"]

        # Found a second family -> its founder is a PARENT with tokens.
        r = await client.post("/api/auth/register-family", json={
            "family_name": "Other Family",
            "name": "Other Parent",
            "email": "other-parent@test.com",
            "password": "password123",
            "accept_terms": True,
        })
        assert r.status_code in (200, 201), r.text
        other_token = r.json()["access_token"]
        headers = {"Authorization": f"Bearer {other_token}"}

        r = await client.post(f"/api/users/{pending_id}/approve", headers=headers)
        assert r.status_code == 403, r.text
        r = await client.post(f"/api/users/{pending_id}/reject", headers=headers)
        assert r.status_code == 403, r.text

        # The member still exists and is still pending in family A.
        user = (await db_session.execute(
            select(User).where(User.email == "pending-kid@test.com")
        )).scalar_one()
        assert user.approval_status == APPROVAL_PENDING


class TestGoogleOAuthApprovalAndConsent:
    """Google OAuth must not bypass the join-code approval gate or the
    founder-consent requirement (review fix, 2026-07-07)."""

    @staticmethod
    def _ginfo(email: str, name: str = "G Kid") -> dict:
        return {
            "google_id": f"gid-{email}",
            "email": email,
            "name": name,
            "email_verified": True,
        }

    @pytest.mark.asyncio
    async def test_oauth_join_code_signup_pending_no_tokens_role_capped(
        self, client, db_session, test_family, test_parent_user
    ):
        """OAuth signup with join_code + role='parent' -> account created
        PENDING as CHILD (never parent), no tokens, parents notified."""
        from app.core.exceptions import ForbiddenException
        from app.services.google_oauth_service import GoogleOAuthService

        code = await _join_code_for(db_session, test_family)
        with pytest.raises(ForbiddenException):
            await GoogleOAuthService.authenticate_or_create_user(
                db_session,
                self._ginfo("g-pending@test.com"),
                join_code=code,
                role="parent",  # must be demoted, never honored
            )

        user = (await db_session.execute(
            select(User).where(User.email == "g-pending@test.com")
        )).scalar_one()
        assert user.role == UserRole.CHILD
        assert user.approval_status == APPROVAL_PENDING
        assert user.approved_at is None

        notes = (await db_session.execute(
            select(Notification).where(
                Notification.user_id == test_parent_user.id,
                Notification.type == "member_pending_approval",
            )
        )).scalars().all()
        assert len(notes) == 1

    @pytest.mark.asyncio
    async def test_oauth_route_join_code_returns_403_no_tokens(
        self, client, db_session, test_family, test_parent_user, monkeypatch
    ):
        """Route-level: POST /api/oauth/google with a join_code -> 403 with
        the pending message and NO auth tokens in the body."""
        from app.services.google_oauth_service import GoogleOAuthService

        async def fake_verify(token):
            return self._ginfo("g-route-pending@test.com", "Route Kid")

        monkeypatch.setattr(
            GoogleOAuthService, "verify_google_token", staticmethod(fake_verify)
        )

        code = await _join_code_for(db_session, test_family)
        r = await client.post("/api/oauth/google", json={
            "token": "fake", "join_code": code, "role": "parent",
        })
        assert r.status_code == 403, r.text
        body = r.json()
        assert "access_token" not in body
        msg = (body.get("message") or body.get("detail") or "").lower()
        assert "pending" in msg or "pendiente" in msg

        user = (await db_session.execute(
            select(User).where(User.email == "g-route-pending@test.com")
        )).scalar_one()
        assert user.role == UserRole.CHILD
        assert user.approval_status == APPROVAL_PENDING

    @pytest.mark.asyncio
    async def test_oauth_login_blocked_while_pending_same_email(
        self, client, db_session, test_family, test_parent_user
    ):
        """A kid pending from the join-code register form cannot get in by
        'Sign in with Google' with the same email (existing-user branch)."""
        from app.core.exceptions import ForbiddenException
        from app.services.google_oauth_service import GoogleOAuthService

        code = await _join_code_for(db_session, test_family)
        r = await _register_join(client, code)
        assert r.status_code in (200, 201)

        with pytest.raises(ForbiddenException):
            await GoogleOAuthService.authenticate_or_create_user(
                db_session,
                self._ginfo("pending-kid@test.com", "Pending Kid"),
            )

    @pytest.mark.asyncio
    async def test_oauth_new_family_requires_consent(self, client, db_session):
        """Bare OAuth signup that would CREATE a family is blocked until
        accept_terms is sent — no account/family is created."""
        from app.core.exceptions import ValidationException
        from app.services.google_oauth_service import GoogleOAuthService

        with pytest.raises(ValidationException):
            await GoogleOAuthService.authenticate_or_create_user(
                db_session,
                self._ginfo("g-noconsent@test.com", "No Consent"),
            )

        user = (await db_session.execute(
            select(User).where(User.email == "g-noconsent@test.com")
        )).scalar_one_or_none()
        assert user is None

    @pytest.mark.asyncio
    async def test_oauth_new_family_with_consent_is_stamped(
        self, client, db_session
    ):
        """OAuth founder with accept_terms=True gets tokens and the consent
        timestamp + policy version are recorded."""
        from app.services.google_oauth_service import GoogleOAuthService

        user, access_token, refresh_token, is_new = (
            await GoogleOAuthService.authenticate_or_create_user(
                db_session,
                self._ginfo("g-consent@test.com", "Consenting Founder"),
                accept_terms=True,
            )
        )
        assert is_new is True
        assert access_token and refresh_token
        assert user.role == UserRole.PARENT
        assert user.approval_status == APPROVAL_APPROVED
        assert user.consented_at is not None
        assert user.consent_policy_version == CONSENT_POLICY_VERSION
