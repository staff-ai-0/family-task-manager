"""UX-D4a: the app-icon number — what is waiting for this user."""
import json
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from app.models.family import Family
from app.models.gig import GigClaim, GigClaimStatus, GigOffering
from app.models.push_subscription import PushSubscription
from app.models.reward import RedemptionStatus, RewardRedemption
from app.models.task_assignment import ApprovalStatus, AssignmentStatus, TaskAssignment
from app.models.task_template import AssignmentType, TaskTemplate
from app.models.user import User, UserRole
from app.services.gig_claim_service import GigClaimService
from app.services.ping_service import PingService
from app.services.progress_service import ProgressService
from app.services.push_service import PushService
from app.services.reward_service import RewardService
from app.services.task_assignment_service import TaskAssignmentService


async def _login(client, email):
    r = await client.post("/api/auth/login", json={"email": email, "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _template(db, family_id, *, bonus=False):
    t = TaskTemplate(id=uuid4(), title="Chore", points=10, interval_days=1,
                     assignment_type=AssignmentType.AUTO, is_bonus=bonus, is_active=True, family_id=family_id)
    db.add(t)
    await db.commit()
    return t


async def _assign(db, user, template, day, status=AssignmentStatus.PENDING, approval=ApprovalStatus.NONE):
    a = TaskAssignment(family_id=template.family_id, template_id=template.id, assigned_to=user.id,
                       status=status, approval_status=approval, assigned_date=day,
                       week_of=day - timedelta(days=day.weekday()))
    db.add(a)
    await db.commit()
    return a


async def _other_family_kid(db):
    other = Family(name="Other")
    db.add(other)
    await db.commit()
    kid = User(email="otherkid@test.com", password_hash="x", name="Other Kid", role=UserRole.CHILD,
               family_id=other.id, email_verified=True, points=0)
    db.add(kid)
    await db.commit()
    return other, kid


class TestKidCount:
    async def test_open_chores_today_plus_carried_over(self, db_session, test_family, test_child_user, test_teen_user):
        kid = test_child_user
        today, _tz = await ProgressService.family_today(db_session, kid.family_id)
        chore = await _template(db_session, kid.family_id)
        bonus = await _template(db_session, kid.family_id, bonus=True)
        await _assign(db_session, kid, chore, today)
        await _assign(db_session, kid, chore, today)
        await _assign(db_session, kid, chore, today - timedelta(days=1), AssignmentStatus.OVERDUE)
        await _assign(db_session, kid, chore, today - timedelta(days=9), AssignmentStatus.OVERDUE)
        await _assign(db_session, kid, chore, today, AssignmentStatus.COMPLETED)      # done: not waiting
        await _assign(db_session, kid, chore, today, AssignmentStatus.CANCELLED)      # cancelled
        await _assign(db_session, kid, chore, today + timedelta(days=1))              # tomorrow
        await _assign(db_session, kid, bonus, today)                                  # optional
        await _assign(db_session, test_teen_user, chore, today)                       # a sibling's
        assert await PingService.waiting_count(db_session, kid) == 4
        assert await PingService.waiting_count(db_session, test_teen_user) == 1

    async def test_it_equals_what_the_kid_home_lists(self, db_session, test_family, test_child_user):
        kid = test_child_user
        today, _tz = await ProgressService.family_today(db_session, kid.family_id)
        chore = await _template(db_session, kid.family_id)
        await _assign(db_session, kid, chore, today)
        await _assign(db_session, kid, chore, today, AssignmentStatus.COMPLETED)
        await _assign(db_session, kid, chore, today - timedelta(days=2), AssignmentStatus.OVERDUE)
        progress = await TaskAssignmentService.get_daily_progress(db_session, kid.id, kid.family_id)
        on_screen = len(progress["overdue_assignments"]) + sum(
            1 for a in progress["assignments"]
            if not a.template.is_bonus and a.status in (AssignmentStatus.PENDING, AssignmentStatus.OVERDUE)
        )
        assert await PingService.waiting_count(db_session, kid) == on_screen == 2

    async def test_another_familys_chores_never_count(self, db_session, test_family, test_child_user):
        other, other_kid = await _other_family_kid(db_session)
        today, _tz = await ProgressService.family_today(db_session, other.id)
        theirs = await _template(db_session, other.id)
        await _assign(db_session, other_kid, theirs, today)
        # A row that names our kid but lives in the other family must not leak in.
        db_session.add(TaskAssignment(family_id=other.id, template_id=theirs.id, assigned_to=test_child_user.id,
                                      status=AssignmentStatus.PENDING, approval_status=ApprovalStatus.NONE,
                                      assigned_date=today, week_of=today - timedelta(days=today.weekday())))
        await db_session.commit()
        assert await PingService.waiting_count(db_session, test_child_user) == 0


class TestParentCount:
    async def _queue(self, db, family_id, kid):
        today, _tz = await ProgressService.family_today(db, family_id)
        chore = await _template(db, family_id)
        await _assign(db, kid, chore, today, AssignmentStatus.COMPLETED, ApprovalStatus.PENDING)
        await _assign(db, kid, chore, today, AssignmentStatus.COMPLETED, ApprovalStatus.APPROVED)
        gig = GigOffering(family_id=family_id, title="Wash car", points=50)
        db.add(gig)
        await db.commit()
        db.add_all([
            GigClaim(gig_id=gig.id, family_id=family_id, claimed_by=kid.id, status=GigClaimStatus.COMPLETED),
            RewardRedemption(family_id=family_id, user_id=kid.id, reward_title="Movie", points_cost=10,
                             status=RedemptionStatus.PENDING.value),
            RewardRedemption(family_id=family_id, user_id=kid.id, reward_title="Old", points_cost=10,
                             status=RedemptionStatus.APPROVED.value),
        ])
        await db.commit()

    async def test_three_review_queues(self, db_session, test_family, test_parent_user, test_child_user):
        await self._queue(db_session, test_family.id, test_child_user)
        assert await PingService.waiting_count(db_session, test_parent_user) == 3

    async def test_it_equals_the_approvals_page(self, db_session, test_family, test_parent_user, test_child_user):
        await self._queue(db_session, test_family.id, test_child_user)
        fid = test_family.id
        page = (
            len(await TaskAssignmentService.list_pending_approvals(db_session, fid))
            + len(await GigClaimService.get_pending_approvals(db_session, fid))
            + len(await RewardService.list_pending_redemptions(db_session, fid))
        )
        assert await PingService.waiting_count(db_session, test_parent_user) == page == 3

    async def test_another_familys_queue_never_counts(self, db_session, test_family, test_parent_user):
        other, other_kid = await _other_family_kid(db_session)
        await self._queue(db_session, other.id, other_kid)
        assert await PingService.waiting_count(db_session, test_parent_user) == 0


class TestEndpoint:
    async def test_requires_auth(self, client):
        assert (await client.get("/api/notifications/waiting-count")).status_code in (401, 403)

    async def test_kid_and_parent(self, client, db_session, test_family, test_parent_user, test_child_user):
        today, _tz = await ProgressService.family_today(db_session, test_family.id)
        chore = await _template(db_session, test_family.id)
        await _assign(db_session, test_child_user, chore, today)
        await _assign(db_session, test_child_user, chore, today, AssignmentStatus.COMPLETED, ApprovalStatus.PENDING)
        r = await client.get("/api/notifications/waiting-count", headers=await _login(client, "child@test.com"))
        assert r.status_code == 200 and r.json() == {"count": 1}
        r = await client.get("/api/notifications/waiting-count", headers=await _login(client, "parent@test.com"))
        assert r.json() == {"count": 1}
        assert isinstance(r.json()["count"], int)


class TestPushCarriesTheCount:
    async def _subscribed(self, db, user):
        from app.core.config import settings
        settings.VAPID_PRIVATE_KEY = "fake-private-pem"
        settings.VAPID_PUBLIC_KEY = "fake-public"
        db.add(PushSubscription(user_id=user.id, endpoint=f"https://push.example/{uuid4()}", p256dh="p", auth="a"))
        await db.commit()

    def _reset(self):
        from app.core.config import settings
        settings.VAPID_PRIVATE_KEY = ""
        settings.VAPID_PUBLIC_KEY = ""

    async def test_badge_is_the_recipients_count(self, db_session, test_family, test_child_user):
        today, _tz = await ProgressService.family_today(db_session, test_family.id)
        chore = await _template(db_session, test_family.id)
        await _assign(db_session, test_child_user, chore, today)
        await _assign(db_session, test_child_user, chore, today)
        await self._subscribed(db_session, test_child_user)
        try:
            with patch("app.services.push_service.webpush") as mock_webpush:
                await PushService.send_to_user(db_session, test_child_user.id, {"title": "x", "body": "y"})
            sent = json.loads(mock_webpush.call_args.kwargs["data"])
            assert sent["badge"] == 2 and sent["title"] == "x"
        finally:
            self._reset()

    async def test_a_callers_own_badge_is_kept(self, db_session, test_family, test_child_user):
        await self._subscribed(db_session, test_child_user)
        try:
            with patch("app.services.push_service.webpush") as mock_webpush:
                await PushService.send_to_user(db_session, test_child_user.id, {"title": "x", "badge": 7})
            assert json.loads(mock_webpush.call_args.kwargs["data"])["badge"] == 7
        finally:
            self._reset()

    async def test_a_failing_count_still_sends_the_push(self, db_session, test_family, test_child_user):
        await self._subscribed(db_session, test_child_user)
        try:
            with patch("app.services.push_service.webpush") as mock_webpush, \
                 patch("app.services.ping_service.PingService.waiting_count_for_id", side_effect=RuntimeError("boom")):
                n = await PushService.send_to_user(db_session, test_child_user.id, {"title": "x", "body": "y"})
            assert n == 1 and mock_webpush.call_count == 1
            assert "badge" not in json.loads(mock_webpush.call_args.kwargs["data"])
        finally:
            self._reset()

    async def test_the_callers_payload_dict_is_not_mutated(self, db_session, test_family, test_child_user):
        await self._subscribed(db_session, test_child_user)
        payload = {"title": "x", "body": "y"}
        try:
            with patch("app.services.push_service.webpush"):
                await PushService.send_to_user(db_session, test_child_user.id, payload)
            assert payload == {"title": "x", "body": "y"}
        finally:
            self._reset()
