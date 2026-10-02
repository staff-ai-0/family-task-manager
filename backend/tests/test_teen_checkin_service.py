"""Jarvis teen check-in against the test DB. Dates derive from the family's today."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from sqlalchemy import func, select

from app.models.family import Family
from app.models.task_assignment import ApprovalStatus, AssignmentStatus, TaskAssignment
from app.models.task_template import AssignmentType, TaskTemplate
from app.models.teen_checkin import TeenCheckin
from app.models.user import User, UserRole
from app.services.progress_service import ProgressService
from app.services.teen_checkin_service import TeenCheckinService


async def _today(db, family_id):
    today, _tz = await ProgressService.family_today(db, family_id)
    return today


async def _on(db, family, value=True):
    family.teen_checkin_enabled = value
    await db.commit()


async def _template(db, family_id, *, bonus=False, title="Take out the trash", title_es="Saca la basura", points=15):
    t = TaskTemplate(id=uuid4(), title=title, title_es=title_es, points=points, interval_days=1,
                     assignment_type=AssignmentType.AUTO, is_bonus=bonus, is_active=True, family_id=family_id)
    db.add(t)
    await db.commit()
    return t


async def _assign(db, user, template, day, status=AssignmentStatus.OVERDUE, approval=ApprovalStatus.NONE,
                  grade=None):
    a = TaskAssignment(family_id=template.family_id, template_id=template.id, assigned_to=user.id,
                       status=status, approval_status=approval, completion_grade=grade,
                       assigned_date=day, week_of=day - timedelta(days=day.weekday()))
    db.add(a)
    await db.commit()
    return a


async def _count(db):
    return (await db.execute(select(func.count()).select_from(TeenCheckin))).scalar()


async def _past_row(db, teen, *, days_ago, outcome="answered"):
    db.add(TeenCheckin(family_id=teen.family_id, user_id=teen.id, assignment_id=None, trigger="late",
                       outcome=outcome, reason="forgot" if outcome == "answered" else None, days_late=1,
                       points=10, lang="en", created_at=datetime.now(timezone.utc) - timedelta(days=days_ago)))
    await db.commit()


class TestOffer:
    async def test_a_late_chore_is_offered(self, db_session, test_family, test_teen_user):
        await _on(db_session, test_family)
        today = await _today(db_session, test_family.id)
        chore = await _template(db_session, test_family.id)
        a = await _assign(db_session, test_teen_user, chore, today - timedelta(days=2))
        offer = await TeenCheckinService.offer_for(db_session, test_teen_user)
        assert offer is not None and offer.assignment_id == a.id
        assert (offer.trigger, offer.title, offer.title_es, offer.points) == ("late", "Take out the trash", "Saca la basura", 15)
        assert await _count(db_session) == 0                       # reading the offer stores nothing

    async def test_a_sent_back_chore_wins_and_may_be_dated_today(self, db_session, test_family, test_teen_user):
        await _on(db_session, test_family)
        today = await _today(db_session, test_family.id)
        chore = await _template(db_session, test_family.id)
        await _assign(db_session, test_teen_user, chore, today - timedelta(days=1))
        back = await _assign(db_session, test_teen_user, chore, today, AssignmentStatus.PENDING,
                             ApprovalStatus.REJECTED, grade="missed")
        offer = await TeenCheckinService.offer_for(db_session, test_teen_user)
        assert offer.assignment_id == back.id and offer.trigger == "sent_back"

    async def test_undecided_and_off_families_get_nothing(self, db_session, test_family, test_teen_user):
        today = await _today(db_session, test_family.id)
        chore = await _template(db_session, test_family.id)
        await _assign(db_session, test_teen_user, chore, today - timedelta(days=1))
        assert await TeenCheckinService.offer_for(db_session, test_teen_user) is None      # NULL = undecided
        await _on(db_session, test_family, False)
        assert await TeenCheckinService.offer_for(db_session, test_teen_user) is None

    async def test_only_teens(self, db_session, test_family, test_child_user, test_parent_user):
        await _on(db_session, test_family)
        today = await _today(db_session, test_family.id)
        chore = await _template(db_session, test_family.id)
        for user in (test_child_user, test_parent_user):
            await _assign(db_session, user, chore, today - timedelta(days=1))
            assert await TeenCheckinService.offer_for(db_session, user) is None

    async def test_what_is_never_a_candidate(self, db_session, test_family, test_teen_user):
        await _on(db_session, test_family)
        today = await _today(db_session, test_family.id)
        chore = await _template(db_session, test_family.id)
        bonus = await _template(db_session, test_family.id, bonus=True)
        teen = test_teen_user
        await _assign(db_session, teen, bonus, today - timedelta(days=1))                       # optional work
        await _assign(db_session, teen, chore, today - timedelta(days=1), AssignmentStatus.COMPLETED)
        await _assign(db_session, teen, chore, today - timedelta(days=1), AssignmentStatus.CANCELLED)
        await _assign(db_session, teen, chore, today, AssignmentStatus.PENDING)                 # today, not late
        await _assign(db_session, teen, chore, today - timedelta(days=14))                      # too old
        assert await TeenCheckinService.offer_for(db_session, teen) is None
        edge = await _assign(db_session, teen, chore, today - timedelta(days=13))               # 14th day back
        assert (await TeenCheckinService.offer_for(db_session, teen)).assignment_id == edge.id

    async def test_a_siblings_or_another_familys_chore_is_never_offered(self, db_session, test_family, test_teen_user, test_child_user):
        await _on(db_session, test_family)
        today = await _today(db_session, test_family.id)
        chore = await _template(db_session, test_family.id)
        await _assign(db_session, test_child_user, chore, today - timedelta(days=1))
        other = Family(name="Other", teen_checkin_enabled=True)
        db_session.add(other)
        await db_session.commit()
        theirs = await _template(db_session, other.id)
        # A row that names our teen but belongs to the other family must not leak in.
        db_session.add(TaskAssignment(family_id=other.id, template_id=theirs.id, assigned_to=test_teen_user.id,
                                      status=AssignmentStatus.OVERDUE, approval_status=ApprovalStatus.NONE,
                                      assigned_date=today - timedelta(days=1),
                                      week_of=today - timedelta(days=today.weekday() + 7)))
        await db_session.commit()
        assert await TeenCheckinService.offer_for(db_session, test_teen_user) is None

    async def test_a_chore_already_asked_about_is_not_offered_again(self, db_session, test_family, test_teen_user):
        await _on(db_session, test_family)
        today = await _today(db_session, test_family.id)
        chore = await _template(db_session, test_family.id)
        a = await _assign(db_session, test_teen_user, chore, today - timedelta(days=3))
        db_session.add(TeenCheckin(family_id=test_family.id, user_id=test_teen_user.id, assignment_id=a.id,
                                   trigger="late", outcome="answered", reason="forgot", days_late=1, points=15,
                                   lang="en", created_at=datetime.now(timezone.utc) - timedelta(days=2)))
        await db_session.commit()
        assert await TeenCheckinService.offer_for(db_session, test_teen_user) is None     # still late, already asked
        fresh = await _assign(db_session, test_teen_user, chore, today - timedelta(days=1))
        assert (await TeenCheckinService.offer_for(db_session, test_teen_user)).assignment_id == fresh.id

    async def test_a_recent_not_now_pauses_and_an_old_one_does_not(self, db_session, test_family, test_teen_user):
        await _on(db_session, test_family)
        today = await _today(db_session, test_family.id)
        chore = await _template(db_session, test_family.id)
        await _assign(db_session, test_teen_user, chore, today - timedelta(days=1))
        await _past_row(db_session, test_teen_user, days_ago=8, outcome="dismissed")
        assert await TeenCheckinService.offer_for(db_session, test_teen_user) is not None
        await _past_row(db_session, test_teen_user, days_ago=3, outcome="dismissed")
        assert await TeenCheckinService.offer_for(db_session, test_teen_user) is None


class TestRecord:
    async def _offered(self, db, family, teen, **kw):
        await _on(db, family)
        today = await _today(db, family.id)
        chore = await _template(db, family.id, **kw)
        return await _assign(db, teen, chore, today - timedelta(days=2))

    async def test_an_answer_is_stored_without_the_title(self, db_session, test_family, test_teen_user):
        a = await self._offered(db_session, test_family, test_teen_user, title="Clean Diego's room", points=25)
        assert await TeenCheckinService.record(db_session, test_teen_user, a.id, "answered", "not_fair", None) is True
        row = (await db_session.execute(select(TeenCheckin))).scalar_one()
        assert (row.family_id, row.user_id, row.assignment_id) == (test_family.id, test_teen_user.id, a.id)
        assert (row.trigger, row.outcome, row.reason, row.note) == ("late", "answered", "not_fair", None)
        assert (row.days_late, row.points, row.lang) == (2, 25, "en")
        stored = " ".join(str(v) for v in vars(row).values())
        assert "Diego" not in stored

    async def test_a_note_is_kept_for_an_open_reason_and_the_language_follows_the_teen(self, db_session, test_family, test_teen_user):
        test_teen_user.preferred_lang = "es-MX"
        await db_session.commit()
        a = await self._offered(db_session, test_family, test_teen_user)
        await TeenCheckinService.record(db_session, test_teen_user, a.id, "answered", "app_problem", "  no abre la cámara ")
        row = (await db_session.execute(select(TeenCheckin))).scalar_one()
        assert (row.reason, row.note, row.lang) == ("app_problem", "no abre la cámara", "es")

    async def test_not_now_is_stored_and_nothing_more_is_offered_today(self, db_session, test_family, test_teen_user):
        a = await self._offered(db_session, test_family, test_teen_user)
        chore2 = await _template(db_session, test_family.id, title="Dishes")
        today = await _today(db_session, test_family.id)
        await _assign(db_session, test_teen_user, chore2, today - timedelta(days=1))
        offer = await TeenCheckinService.offer_for(db_session, test_teen_user)
        assert await TeenCheckinService.record(db_session, test_teen_user, offer.assignment_id, "dismissed", None, None) is True
        row = (await db_session.execute(select(TeenCheckin))).scalar_one()
        assert (row.outcome, row.reason) == ("dismissed", None)
        assert await TeenCheckinService.offer_for(db_session, test_teen_user) is None
        assert offer.assignment_id != a.id                         # the more recent chore was the one offered

    async def test_after_an_answer_nothing_more_is_offered_today(self, db_session, test_family, test_teen_user):
        await self._offered(db_session, test_family, test_teen_user)
        today = await _today(db_session, test_family.id)
        other = await _template(db_session, test_family.id, title="Dishes")
        await _assign(db_session, test_teen_user, other, today - timedelta(days=1))
        offer = await TeenCheckinService.offer_for(db_session, test_teen_user)
        await TeenCheckinService.record(db_session, test_teen_user, offer.assignment_id, "answered", "forgot", None)
        assert await TeenCheckinService.offer_for(db_session, test_teen_user) is None

    async def test_saving_twice_is_harmless(self, db_session, test_family, test_teen_user):
        a = await self._offered(db_session, test_family, test_teen_user)
        assert await TeenCheckinService.record(db_session, test_teen_user, a.id, "answered", "forgot", None) is True
        assert await TeenCheckinService.record(db_session, test_teen_user, a.id, "answered", "too_hard", None) is True
        row = (await db_session.execute(select(TeenCheckin))).scalar_one()
        assert row.reason == "forgot"                              # the first answer stands

    async def test_only_the_current_offer_can_be_answered(self, db_session, test_family, test_teen_user, test_child_user):
        await _on(db_session, test_family)
        today = await _today(db_session, test_family.id)
        chore = await _template(db_session, test_family.id)
        older = await _assign(db_session, test_teen_user, chore, today - timedelta(days=5))
        await _assign(db_session, test_teen_user, chore, today - timedelta(days=1))               # the offer
        siblings = await _assign(db_session, test_child_user, chore, today - timedelta(days=1))
        not_late = await _assign(db_session, test_teen_user, chore, today, AssignmentStatus.PENDING)
        for bad in (older.id, siblings.id, not_late.id, uuid4()):
            assert await TeenCheckinService.record(db_session, test_teen_user, bad, "answered", "forgot", None) is False
        assert await _count(db_session) == 0

    async def test_another_familys_chore_cannot_be_answered(self, db_session, test_family, test_teen_user):
        await _on(db_session, test_family)
        other = Family(name="Other", teen_checkin_enabled=True)
        db_session.add(other)
        await db_session.commit()
        other_teen = User(email="otherteen@test.com", password_hash="x", name="Other Teen", role=UserRole.TEEN,
                          family_id=other.id, email_verified=True, points=0)
        db_session.add(other_teen)
        await db_session.commit()
        today = await _today(db_session, other.id)
        theirs = await _assign(db_session, other_teen, await _template(db_session, other.id), today - timedelta(days=1))
        assert await TeenCheckinService.record(db_session, test_teen_user, theirs.id, "answered", "forgot", None) is False
        assert await _count(db_session) == 0

    async def test_a_family_that_is_off_stores_nothing(self, db_session, test_family, test_teen_user):
        a = await self._offered(db_session, test_family, test_teen_user)
        await _on(db_session, test_family, None)
        assert await TeenCheckinService.record(db_session, test_teen_user, a.id, "answered", "forgot", None) is False
        assert await _count(db_session) == 0

    async def test_a_parent_or_child_can_never_store_a_row(self, db_session, test_family, test_parent_user, test_child_user, test_teen_user):
        a = await self._offered(db_session, test_family, test_teen_user)
        for user in (test_parent_user, test_child_user):
            assert await TeenCheckinService.record(db_session, user, a.id, "answered", "forgot", None) is False
        assert await _count(db_session) == 0


class TestCanChat:
    async def test_follows_the_plan(self, db_session, test_family):
        with patch("app.services.teen_checkin_service.family_tier_allows", new=AsyncMock(return_value=True)) as allows:
            assert await TeenCheckinService.can_chat(db_session, test_family.id) is True
        allows.assert_awaited_once_with(db_session, test_family.id, "ai_features")
        assert await TeenCheckinService.can_chat(db_session, test_family.id) is False             # free plan
