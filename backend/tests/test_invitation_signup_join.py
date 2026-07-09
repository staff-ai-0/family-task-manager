"""Signup paths must honor a pending email invitation instead of minting a
new family.

Regression tests for the invitation-bypass bug: a parent invites someone by
email (a PENDING ``FamilyInvitation`` keyed on ``invited_email``), but the
invitee signs up via "Sign in with Google" or the register form instead of the
emailed ``/accept-invitation?code=…`` link. Before the fix, those paths always
created a brand-new family (google_oauth_service Priority 3 / register-family
``else`` branch) and never consulted the invitation — so two people who should
share a family ended up split.

After the fix:
- Google OAuth and register-family, when no join_code/family_id/family_code is
  supplied, look up a valid PENDING invitation for the email and JOIN that
  family (with the invitation's role, APPROVED, invitation marked accepted),
  falling through to auto-create only when there is no invitation.
- ``POST /api/invitations/accept`` reconciles an already-registered invitee
  (moves the existing account into the inviter's family) instead of blindly
  INSERTing a duplicate and 400ing on the unique-email constraint.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.models.family import Family
from app.models.invitation import FamilyInvitation, InvitationStatus
from app.models.user import User, UserRole
from app.services.google_oauth_service import GoogleOAuthService


def _ginfo(email: str, name: str = "Invited Spouse") -> dict:
    return {
        "google_id": f"gid-{email}",
        "email": email,
        "name": name,
        "email_verified": True,
    }


def _mock_verify(monkeypatch, email: str, name: str = "Invited Spouse") -> None:
    async def fake_verify(token):
        return _ginfo(email, name)

    monkeypatch.setattr(
        GoogleOAuthService, "verify_google_token", staticmethod(fake_verify)
    )


async def _make_pending_invite(
    db_session, family, inviter, email: str, role: UserRole = UserRole.PARENT
) -> FamilyInvitation:
    inv = FamilyInvitation(
        family_id=family.id,
        invited_email=email,
        invited_by_user_id=inviter.id,
        invitation_code=FamilyInvitation.generate_code(),
        status=InvitationStatus.PENDING,
        role=role,
        expires_at=datetime.now(timezone.utc).replace(tzinfo=None)
        + timedelta(days=30),
    )
    db_session.add(inv)
    await db_session.commit()
    await db_session.refresh(inv)
    return inv


async def _family_count(db_session) -> int:
    return (await db_session.execute(select(func.count(Family.id)))).scalar_one()


class TestGoogleOAuthHonorsInvite:
    @pytest.mark.asyncio
    async def test_new_google_user_with_pending_invite_joins_inviter_family(
        self, db_session, test_family, test_parent_user
    ):
        email = "spouse@test.com"
        inv = await _make_pending_invite(
            db_session, test_family, test_parent_user, email, UserRole.PARENT
        )
        before = await _family_count(db_session)

        user, access, refresh, is_new = (
            await GoogleOAuthService.authenticate_or_create_user(
                db_session, _ginfo(email)
            )
        )

        assert is_new is True
        # Joined the inviter's family — NOT a fresh one
        assert user.family_id == test_family.id
        assert user.role == UserRole.PARENT
        assert access and refresh  # tokens issued (approved, no pending gate)
        assert await _family_count(db_session) == before  # no new family minted

        await db_session.refresh(inv)
        assert inv.status == InvitationStatus.ACCEPTED
        assert inv.accepted_by_user_id == user.id

    @pytest.mark.asyncio
    async def test_new_google_user_without_invite_still_creates_family(
        self, db_session, test_family, test_parent_user
    ):
        before = await _family_count(db_session)

        user, access, refresh, is_new = (
            await GoogleOAuthService.authenticate_or_create_user(
                db_session, _ginfo("stranger@test.com"), accept_terms=True
            )
        )

        assert is_new is True
        assert user.family_id != test_family.id  # brand-new family
        assert user.role == UserRole.PARENT
        assert await _family_count(db_session) == before + 1


class TestRegisterFamilyHonorsInvite:
    @pytest.mark.asyncio
    async def test_register_with_pending_invite_joins_without_family_name(
        self, client, db_session, test_family, test_parent_user
    ):
        email = "spouse2@test.com"
        inv = await _make_pending_invite(
            db_session, test_family, test_parent_user, email, UserRole.PARENT
        )
        before = await _family_count(db_session)

        # No family_code and no family_name — a pending invite should carry it.
        r = await client.post(
            "/api/auth/register-family",
            json={"email": email, "name": "Spouse Two", "password": "password123"},
        )
        assert r.status_code == 201, r.text

        joined = (
            await db_session.execute(select(User).where(User.email == email))
        ).scalar_one()
        assert joined.family_id == test_family.id
        assert joined.role == UserRole.PARENT
        assert await _family_count(db_session) == before  # no new family

        await db_session.refresh(inv)
        assert inv.status == InvitationStatus.ACCEPTED

    @pytest.mark.asyncio
    async def test_register_without_invite_still_creates_family(
        self, client, db_session, test_family, test_parent_user
    ):
        before = await _family_count(db_session)
        r = await client.post(
            "/api/auth/register-family",
            json={
                "email": "founder@test.com",
                "name": "Founder",
                "password": "password123",
                "family_name": "Founder Family",
                "accept_terms": True,
            },
        )
        assert r.status_code == 201, r.text
        assert await _family_count(db_session) == before + 1


class TestAcceptReconcilesExistingUser:
    @pytest.mark.asyncio
    async def test_accept_moves_already_registered_user_into_inviter_family(
        self, client, db_session, test_family, test_parent_user
    ):
        # Invitee already has their own account in their own family.
        own_family = Family(name="Own Family")
        db_session.add(own_family)
        await db_session.commit()
        await db_session.refresh(own_family)
        from app.core.security import get_password_hash

        existing = User(
            email="already@test.com",
            password_hash=get_password_hash("password123"),
            name="Already Registered",
            role=UserRole.PARENT,
            family_id=own_family.id,
            email_verified=True,
            points=0,
        )
        db_session.add(existing)
        await db_session.commit()
        await db_session.refresh(existing)
        existing_id = existing.id

        inv = await _make_pending_invite(
            db_session, test_family, test_parent_user, "already@test.com",
            UserRole.PARENT,
        )

        r = await client.post(
            "/api/invitations/accept",
            json={
                "invitation_code": inv.invitation_code,
                "name": "Already Registered",
                "password": "password123",
            },
        )
        assert r.status_code == 200, r.text

        # Same account (no duplicate) — now in the inviter's family.
        rows = (
            await db_session.execute(
                select(User).where(User.email == "already@test.com")
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].id == existing_id
        assert rows[0].family_id == test_family.id

        await db_session.refresh(inv)
        assert inv.status == InvitationStatus.ACCEPTED
