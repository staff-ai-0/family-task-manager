"""A gig becoming claimable notifies the kids who may claim it (UX-C1).

Three paths make a gig visible: a parent posts it (create), a parent approves
a kid proposal (review_proposal), or a parent edits a pending proposal live
(update with is_active=True — implicit approval). Recipients: participating
members (active AND parent-approved) whose role the gig allows (default
teen+child), never the actor, never the proposer (who already gets
"propuesta aprobada"), never another family.
"""
from unittest.mock import patch

from httpx import AsyncClient
from sqlalchemy import select

from app.core.security import get_password_hash
from app.models.notification import Notification, NotificationType as NT
from app.models.user import User, UserRole
from app.services.gig_offering_service import GigOfferingService


async def _published_for(db, user_id) -> list[Notification]:
    return list((await db.execute(
        select(Notification).where(
            Notification.user_id == user_id,
            Notification.type == NT.GIG_PUBLISHED,
        )
    )).scalars().all())


async def _member(db, family_id, email, role, **over) -> User:
    user = User(
        email=email,
        password_hash=get_password_hash("password123"),
        name=email.split("@")[0],
        role=role,
        family_id=family_id,
        email_verified=True,
        **over,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _post(db, family_id, parent_id, **over):
    return await GigOfferingService.create(
        db, family_id=family_id, created_by=parent_id,
        title=over.pop("title", "Lavar auto"), points=over.pop("points", 80), **over,
    )


class TestGigPublishedRecipients:
    async def test_parent_post_notifies_kids_not_parents(
        self, db_session, test_family, test_parent_user, test_parent_user_2,
        test_teen_user, test_child_user,
    ):
        await _post(db_session, test_family.id, test_parent_user.id)
        for kid in (test_teen_user, test_child_user):
            rows = await _published_for(db_session, kid.id)
            assert len(rows) == 1
            assert "Lavar auto" in rows[0].title
            assert rows[0].link == "/gigs"
            assert "80" in (rows[0].body or "")
        for parent in (test_parent_user, test_parent_user_2):
            assert await _published_for(db_session, parent.id) == []

    async def test_allowed_roles_limit_recipients(
        self, db_session, test_family, test_parent_user, test_teen_user, test_child_user,
    ):
        await _post(db_session, test_family.id, test_parent_user.id, allowed_roles=["teen"])
        assert len(await _published_for(db_session, test_teen_user.id)) == 1
        assert await _published_for(db_session, test_child_user.id) == []

    async def test_inactive_and_pending_members_skipped(
        self, db_session, test_family, test_parent_user,
    ):
        gone = await _member(db_session, test_family.id, "gone.kid@test.com", UserRole.CHILD, is_active=False)
        waiting = await _member(db_session, test_family.id, "waiting.kid@test.com", UserRole.CHILD, approval_status="pending")
        await _post(db_session, test_family.id, test_parent_user.id)
        assert await _published_for(db_session, gone.id) == []
        assert await _published_for(db_session, waiting.id) == []

    async def test_other_family_never_notified(
        self, db_session, test_family, test_parent_user, other_family,
    ):
        stranger = await _member(db_session, other_family.id, "stranger.kid@test.com", UserRole.TEEN)
        await _post(db_session, test_family.id, test_parent_user.id)
        assert await _published_for(db_session, stranger.id) == []


class TestGigPublishedPaths:
    async def test_approved_proposal_notifies_others_not_proposer(
        self, db_session, test_family, test_parent_user, test_teen_user, test_child_user,
    ):
        proposal = await GigOfferingService.propose(
            db_session, family_id=test_family.id, created_by=test_teen_user.id,
            title="Pintar barda", points=120,
        )
        assert await _published_for(db_session, test_child_user.id) == []
        await GigOfferingService.review_proposal(
            db_session, proposal.id, test_family.id, reviewer_id=test_parent_user.id, approve=True,
        )
        assert len(await _published_for(db_session, test_child_user.id)) == 1
        assert await _published_for(db_session, test_teen_user.id) == []

    async def test_rejected_proposal_notifies_nobody(
        self, db_session, test_family, test_parent_user, test_teen_user, test_child_user,
    ):
        proposal = await GigOfferingService.propose(
            db_session, family_id=test_family.id, created_by=test_teen_user.id,
            title="Pintar barda", points=120,
        )
        await GigOfferingService.review_proposal(
            db_session, proposal.id, test_family.id, reviewer_id=test_parent_user.id, approve=False,
        )
        assert await _published_for(db_session, test_child_user.id) == []

    async def test_implicit_approval_via_update_notifies(
        self, db_session, test_family, test_parent_user, test_teen_user, test_child_user,
    ):
        proposal = await GigOfferingService.propose(
            db_session, family_id=test_family.id, created_by=test_teen_user.id,
            title="Pintar barda", points=120,
        )
        await GigOfferingService.update(
            db_session, proposal.id, test_family.id,
            acting_user_id=test_parent_user.id, is_active=True,
        )
        assert len(await _published_for(db_session, test_child_user.id)) == 1
        assert await _published_for(db_session, test_teen_user.id) == []

    async def test_plain_edit_of_live_gig_does_not_renotify(
        self, db_session, test_family, test_parent_user, test_child_user,
    ):
        gig = await _post(db_session, test_family.id, test_parent_user.id)
        await GigOfferingService.update(
            db_session, gig.id, test_family.id, acting_user_id=test_parent_user.id, points=90,
        )
        assert len(await _published_for(db_session, test_child_user.id)) == 1

    async def test_notification_failure_never_blocks_the_post(
        self, db_session, test_family, test_parent_user, test_child_user,
    ):
        with patch(
            "app.services.notification_service.NotificationService.create_localized",
            side_effect=RuntimeError("smtp down"),
        ):
            gig = await _post(db_session, test_family.id, test_parent_user.id)
        assert gig.id is not None and gig.is_active is True
        assert await _published_for(db_session, test_child_user.id) == []


async def test_offering_list_exposes_timestamps(
    client: AsyncClient, auth_headers, db_session, test_family, test_parent_user,
):
    await _post(db_session, test_family.id, test_parent_user.id)
    r = await client.get("/api/gigs/offerings", headers=auth_headers)
    assert r.status_code == 200
    offering = r.json()[0]["offering"]
    assert offering["created_at"]
    assert "reviewed_at" in offering
