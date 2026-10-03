"""UX-D4b mystery box against the test DB: created on a perfect day, opened once, delivered."""
import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.core.exceptions import NotFoundException, ValidationError
from app.models.family import Family
from app.models.mystery import MysteryBox, MysterySurprise
from app.models.point_transaction import PointTransaction, TransactionType as PT
from app.models.task_assignment import ApprovalStatus, AssignmentStatus, TaskAssignment
from app.models.task_template import AssignmentType, TaskTemplate
from app.models.user import User, UserRole
from app.services.mystery_service import MysteryBoxesOff, MysteryService
from app.services.progress_service import ProgressService


async def _today(db, family_id):
    today, _tz = await ProgressService.family_today(db, family_id)
    return today


async def _template(db, family_id, *, bonus=False):
    t = TaskTemplate(id=uuid4(), title="Chore", points=10, interval_days=1, assignment_type=AssignmentType.AUTO,
                     is_bonus=bonus, is_active=True, family_id=family_id)
    db.add(t)
    await db.commit()
    return t


async def _assign(db, kid, template, day, status=AssignmentStatus.COMPLETED, *, grade=None, approval=ApprovalStatus.NONE):
    a = TaskAssignment(family_id=template.family_id, template_id=template.id, assigned_to=kid.id, status=status,
                       approval_status=approval, completion_grade=grade, assigned_date=day,
                       week_of=day - timedelta(days=day.weekday()))
    db.add(a)
    await db.commit()
    return a


async def _perfect_day(db, kid, *, chores=2):
    today = await _today(db, kid.family_id)
    chore = await _template(db, kid.family_id)
    for _ in range(chores):
        await _assign(db, kid, chore, today)
    return today, chore


async def _jar(db, family, parent, *titles):
    out = []
    for t in titles:
        out.append(await MysteryService.add_surprise(db, parent, t, "🎉"))
    return out


async def _boxes(db, kid=None):
    q = select(MysteryBox)
    if kid is not None:
        q = q.where(MysteryBox.user_id == kid.id)
    return list((await db.execute(q.order_by(MysteryBox.day))).scalars().all())


async def _bonus_rows(db, kid):
    return list((await db.execute(
        select(PointTransaction).where(PointTransaction.user_id == kid.id, PointTransaction.type == PT.BONUS)
    )).scalars().all())


class TestCreation:
    async def test_a_perfect_day_creates_one_closed_box(self, db_session, test_family, test_child_user):
        today, _ = await _perfect_day(db_session, test_child_user)
        resp = await MysteryService.sync(db_session, test_child_user)
        assert resp.applies is True and resp.enabled is True
        assert len(resp.unopened) == 1 and resp.unopened[0].day == today and resp.unopened[0].opened is False
        assert resp.opened_today is None
        again = await MysteryService.sync(db_session, test_child_user)
        assert [b.id for b in again.unopened] == [resp.unopened[0].id]
        assert len(await _boxes(db_session)) == 1

    async def test_an_unfinished_day_gives_no_box(self, db_session, test_family, test_child_user):
        today, chore = await _perfect_day(db_session, test_child_user)
        await _assign(db_session, test_child_user, chore, today, AssignmentStatus.PENDING)
        resp = await MysteryService.sync(db_session, test_child_user)
        assert resp.unopened == [] and await _boxes(db_session) == []

    async def test_no_chores_or_bonus_only_gives_no_box(self, db_session, test_family, test_child_user):
        assert (await MysteryService.sync(db_session, test_child_user)).unopened == []
        today = await _today(db_session, test_family.id)
        bonus = await _template(db_session, test_family.id, bonus=True)
        await _assign(db_session, test_child_user, bonus, today)
        assert (await MysteryService.sync(db_session, test_child_user)).unopened == []
        assert await _boxes(db_session) == []

    async def test_a_chore_awaiting_review_still_counts(self, db_session, test_family, test_child_user):
        today = await _today(db_session, test_family.id)
        chore = await _template(db_session, test_family.id)
        await _assign(db_session, test_child_user, chore, today, approval=ApprovalStatus.PENDING)
        assert len((await MysteryService.sync(db_session, test_child_user)).unopened) == 1

    async def test_a_rejected_or_missed_chore_spoils_the_day(self, db_session, test_family, test_child_user):
        today, chore = await _perfect_day(db_session, test_child_user)
        await _assign(db_session, test_child_user, chore, today, grade="missed")
        assert (await MysteryService.sync(db_session, test_child_user)).unopened == []

    async def test_off_and_undecided_families_get_nothing(self, db_session, test_family, test_child_user):
        await _perfect_day(db_session, test_child_user)
        for value in (0, None):
            test_family.mystery_box_points = value
            await db_session.commit()
            resp = await MysteryService.sync(db_session, test_child_user)
            assert resp.applies is True and resp.enabled is False and resp.unopened == []
        assert await _boxes(db_session) == []

    async def test_parents_do_not_apply(self, db_session, test_family, test_parent_user):
        await _perfect_day(db_session, test_parent_user)
        resp = await MysteryService.sync(db_session, test_parent_user)
        assert resp.applies is False and await _boxes(db_session) == []

    async def test_a_perfect_yesterday_first_read_today_still_gets_its_box(self, db_session, test_family, test_child_user):
        # The last chore was finished elsewhere (pet page, parent marked it
        # done) and the kid opens the home after midnight: the streak counts
        # that day, so the box must exist too.
        today = await _today(db_session, test_family.id)
        chore = await _template(db_session, test_family.id)
        await _assign(db_session, test_child_user, chore, today - timedelta(days=1))
        resp = await MysteryService.sync(db_session, test_child_user)
        assert [b.day for b in resp.unopened] == [today - timedelta(days=1)]
        await _assign(db_session, test_child_user, chore, today - timedelta(days=2))    # older: never backfilled
        resp = await MysteryService.sync(db_session, test_child_user)
        assert [b.day for b in resp.unopened] == [today - timedelta(days=1)]

    async def test_a_later_rejection_does_not_take_the_box_back(self, db_session, test_family, test_child_user):
        today, chore = await _perfect_day(db_session, test_child_user)
        box = (await MysteryService.sync(db_session, test_child_user)).unopened[0]
        await MysteryService.open(db_session, test_child_user, box.id)
        await _assign(db_session, test_child_user, chore, today, grade="missed")         # un-perfected afterwards
        resp = await MysteryService.sync(db_session, test_child_user)
        assert resp.opened_today is not None and resp.opened_today.id == box.id
        assert len(await _boxes(db_session)) == 1

    async def test_yesterdays_unopened_box_still_waits(self, db_session, test_family, test_child_user):
        today = await _today(db_session, test_family.id)
        db_session.add(MysteryBox(family_id=test_family.id, user_id=test_child_user.id, day=today - timedelta(days=1),
                                  points=0, created_at=datetime.now(timezone.utc)))
        await db_session.commit()
        await _perfect_day(db_session, test_child_user)
        resp = await MysteryService.sync(db_session, test_child_user)
        assert [b.day for b in resp.unopened] == [today - timedelta(days=1), today]


class TestOpening:
    async def _closed(self, db, kid):
        await _perfect_day(db, kid)
        return (await MysteryService.sync(db, kid)).unopened[0]

    async def test_an_empty_jar_pays_points_once(self, db_session, test_family, test_child_user):
        box = await self._closed(db_session, test_child_user)
        before = int(test_child_user.points)
        view = await MysteryService.open(db_session, test_child_user, box.id)
        assert view.opened is True and view.kind == "points" and 5 <= view.points <= 20
        await db_session.refresh(test_child_user)
        assert test_child_user.points == before + view.points
        rows = await _bonus_rows(db_session, test_child_user)
        assert len(rows) == 1 and rows[0].points == view.points and rows[0].description == "Mystery box"
        again = await MysteryService.open(db_session, test_child_user, box.id)
        assert (again.kind, again.points) == (view.kind, view.points)
        await db_session.refresh(test_child_user)
        assert test_child_user.points == before + view.points             # paid once
        assert len(await _bonus_rows(db_session, test_child_user)) == 1

    async def test_the_points_follow_the_family_maximum_and_language(self, db_session, test_family, test_child_user):
        test_family.mystery_box_points = 4
        test_child_user.preferred_lang = "es"
        await db_session.commit()
        box = await self._closed(db_session, test_child_user)
        view = await MysteryService.open(db_session, test_child_user, box.id)
        assert 1 <= view.points <= 4
        assert (await _bonus_rows(db_session, test_child_user))[0].description == "Caja sorpresa"

    async def test_a_jar_surprise_is_copied_and_pays_nothing(self, db_session, test_family, test_parent_user, test_child_user):
        (dessert,) = await _jar(db_session, test_family, test_parent_user, "Pick dessert tonight")
        box = await self._closed(db_session, test_child_user)
        before = int(test_child_user.points)
        view = await MysteryService.open(db_session, test_child_user, box.id)
        assert (view.kind, view.surprise_title, view.surprise_emoji, view.points) == ("surprise", "Pick dessert tonight", "🎉", 0)
        await db_session.refresh(test_child_user)
        assert test_child_user.points == before and await _bonus_rows(db_session, test_child_user) == []
        row = (await db_session.execute(select(MysteryBox))).scalar_one()
        assert row.surprise_id == dessert.id
        await MysteryService.remove_surprise(db_session, test_family.id, dessert.id)
        db_session.expire_all()
        row = (await db_session.execute(select(MysteryBox))).scalar_one()
        assert row.surprise_title == "Pick dessert tonight" and row.surprise_id is None

    async def test_never_yesterdays_surprise(self, db_session, test_family, test_parent_user, test_child_user):
        a, b = await _jar(db_session, test_family, test_parent_user, "A", "B")
        today = await _today(db_session, test_family.id)
        db_session.add(MysteryBox(family_id=test_family.id, user_id=test_child_user.id, day=today - timedelta(days=1),
                                  kind="surprise", surprise_id=a.id, surprise_title="A", points=0,
                                  opened_at=datetime.now(timezone.utc) - timedelta(days=1),
                                  created_at=datetime.now(timezone.utc) - timedelta(days=1)))
        await db_session.commit()
        box = await self._closed(db_session, test_child_user)
        for _ in range(5):
            view = await MysteryService.open(db_session, test_child_user, box.id)
            assert view.surprise_title == "B"

    async def test_the_content_is_decided_at_opening(self, db_session, test_family, test_parent_user, test_child_user):
        box = await self._closed(db_session, test_child_user)                 # jar empty when the box appeared
        await _jar(db_session, test_family, test_parent_user, "Movie night")
        view = await MysteryService.open(db_session, test_child_user, box.id)
        assert view.kind == "surprise" and view.surprise_title == "Movie night"

    async def test_two_opens_at_once_pay_once(self, db_session, test_family, test_child_user, test_engine):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
        box = await self._closed(db_session, test_child_user)
        before = int(test_child_user.points)
        factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

        async def one():
            async with factory() as s:
                kid = (await s.execute(select(User).where(User.id == test_child_user.id))).scalar_one()
                return await MysteryService.open(s, kid, box.id)

        a, b = await asyncio.gather(one(), one())
        assert (a.kind, a.points) == (b.kind, b.points)
        await db_session.refresh(test_child_user)
        assert test_child_user.points == before + a.points
        assert len(await _bonus_rows(db_session, test_child_user)) == 1

    async def test_only_the_owner_can_open(self, db_session, test_family, test_child_user, test_teen_user):
        box = await self._closed(db_session, test_child_user)
        with pytest.raises(NotFoundException):
            await MysteryService.open(db_session, test_teen_user, box.id)
        with pytest.raises(NotFoundException):
            await MysteryService.open(db_session, test_child_user, uuid4())
        assert (await _boxes(db_session))[0].opened_at is None

    async def test_another_family_cannot_open_it(self, db_session, test_family, test_child_user):
        box = await self._closed(db_session, test_child_user)
        other = Family(name="Other", mystery_box_points=20)
        db_session.add(other)
        await db_session.commit()
        stranger = User(email="stranger@test.com", password_hash="x", name="S", role=UserRole.CHILD, family_id=other.id,
                        email_verified=True, points=0)
        db_session.add(stranger)
        await db_session.commit()
        with pytest.raises(NotFoundException):
            await MysteryService.open(db_session, stranger, box.id)

    async def test_a_family_that_switched_off_cannot_open_until_it_is_on_again(self, db_session, test_family, test_child_user):
        box = await self._closed(db_session, test_child_user)
        test_family.mystery_box_points = 0
        await db_session.commit()
        with pytest.raises(MysteryBoxesOff):
            await MysteryService.open(db_session, test_child_user, box.id)
        assert (await _boxes(db_session))[0].opened_at is None
        test_family.mystery_box_points = 20
        await db_session.commit()
        assert (await MysteryService.open(db_session, test_child_user, box.id)).opened is True

    async def test_sync_reports_todays_opened_box(self, db_session, test_family, test_child_user):
        box = await self._closed(db_session, test_child_user)
        await MysteryService.open(db_session, test_child_user, box.id)
        resp = await MysteryService.sync(db_session, test_child_user)
        assert resp.unopened == [] and resp.opened_today is not None and resp.opened_today.id == box.id

    async def test_a_backlog_box_opened_today_is_todays_reveal(self, db_session, test_family, test_child_user):
        # "Opened today" is about WHEN it was opened, not which day earned it:
        # a kid opening yesterday's waiting box must still see what they got.
        today = await _today(db_session, test_family.id)
        db_session.add(MysteryBox(family_id=test_family.id, user_id=test_child_user.id, day=today - timedelta(days=1),
                                  points=0, created_at=datetime.now(timezone.utc)))
        await db_session.commit()
        old = (await MysteryService.sync(db_session, test_child_user)).unopened[0]
        await MysteryService.open(db_session, test_child_user, old.id)
        resp = await MysteryService.sync(db_session, test_child_user)
        assert resp.unopened == [] and resp.opened_today is not None and resp.opened_today.id == old.id
        # With a second box still waiting, the reveal is still reported.
        await _perfect_day(db_session, test_child_user)
        resp = await MysteryService.sync(db_session, test_child_user)
        assert len(resp.unopened) == 1 and resp.opened_today is not None and resp.opened_today.id == old.id


class TestDeliveries:
    async def test_surprises_wait_for_a_parent_and_points_do_not(self, db_session, test_family, test_parent_user, test_child_user, test_teen_user):
        await _jar(db_session, test_family, test_parent_user, "Pick dessert tonight")
        await _perfect_day(db_session, test_child_user)
        box = (await MysteryService.sync(db_session, test_child_user)).unopened[0]
        await MysteryService.open(db_session, test_child_user, box.id)
        await MysteryService.remove_surprise(db_session, test_family.id,
                                             (await MysteryService.list_surprises(db_session, test_family.id))[0].id)
        await _perfect_day(db_session, test_teen_user)
        teen_box = (await MysteryService.sync(db_session, test_teen_user)).unopened[0]
        await MysteryService.open(db_session, test_teen_user, teen_box.id)         # empty jar → points
        rows = await MysteryService.deliveries(db_session, test_family.id)
        assert [(r.kid_name, r.surprise_title) for r in rows] == [("Test Child", "Pick dessert tonight")]
        await MysteryService.mark_delivered(db_session, test_parent_user, box.id)
        assert await MysteryService.deliveries(db_session, test_family.id) == []
        row = (await db_session.execute(select(MysteryBox).where(MysteryBox.id == box.id))).scalar_one()
        assert row.delivered_at is not None and row.delivered_by == test_parent_user.id

    async def test_another_familys_parent_cannot_mark_it(self, db_session, test_family, test_parent_user, test_child_user):
        await _jar(db_session, test_family, test_parent_user, "X")
        await _perfect_day(db_session, test_child_user)
        box = (await MysteryService.sync(db_session, test_child_user)).unopened[0]
        await MysteryService.open(db_session, test_child_user, box.id)
        other = Family(name="Other")
        db_session.add(other)
        await db_session.commit()
        stranger = User(email="op@test.com", password_hash="x", name="P", role=UserRole.PARENT, family_id=other.id,
                        email_verified=True, points=0)
        db_session.add(stranger)
        await db_session.commit()
        with pytest.raises(NotFoundException):
            await MysteryService.mark_delivered(db_session, stranger, box.id)
        assert len(await MysteryService.deliveries(db_session, test_family.id)) == 1


class TestJar:
    async def test_add_list_remove_scoped_to_the_family(self, db_session, test_family, test_parent_user):
        s = await MysteryService.add_surprise(db_session, test_parent_user, "  Pick dessert tonight  ", "🍨")
        assert (s.title, s.emoji, s.created_by) == ("Pick dessert tonight", "🍨", test_parent_user.id)
        other = Family(name="Other")
        db_session.add(other)
        await db_session.commit()
        db_session.add(MysterySurprise(family_id=other.id, title="Theirs", created_at=datetime.now(timezone.utc)))
        await db_session.commit()
        assert [x.title for x in await MysteryService.list_surprises(db_session, test_family.id)] == ["Pick dessert tonight"]
        with pytest.raises(NotFoundException):
            await MysteryService.remove_surprise(db_session, other.id, s.id)
        await MysteryService.remove_surprise(db_session, test_family.id, s.id)
        assert await MysteryService.list_surprises(db_session, test_family.id) == []

    async def test_limits(self, db_session, test_family, test_parent_user):
        for bad in ("", "   ", "x" * 61):
            with pytest.raises(ValidationError):
                await MysteryService.add_surprise(db_session, test_parent_user, bad, None)
        with pytest.raises(ValidationError):
            await MysteryService.add_surprise(db_session, test_parent_user, "ok", "🎉🎉🎉🎉🎉")   # > 4 code points
        for i in range(20):
            await MysteryService.add_surprise(db_session, test_parent_user, f"s{i}", None)
        with pytest.raises(ValidationError):
            await MysteryService.add_surprise(db_session, test_parent_user, "one too many", None)
        assert (await db_session.execute(select(func.count()).select_from(MysterySurprise))).scalar() == 20
