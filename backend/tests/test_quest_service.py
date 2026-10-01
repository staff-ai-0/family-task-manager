"""UX-D3 weekly quest against the test DB: create, derive, pay once, ack.

Every date is built from the family's "today", so the suite passes on any
weekday (a quest's week is the family-local Monday–Sunday around today).
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import func, select, update

from app.models.family import Family
from app.models.gig import GigClaim, GigClaimStatus, GigOffering, GigOfferingStatus
from app.models.point_transaction import PointTransaction, TransactionType as PT
from app.models.task_assignment import ApprovalStatus, AssignmentStatus, TaskAssignment
from app.models.task_template import AssignmentType, TaskTemplate
from app.models.user import User
from app.models.weekly_quest import WeeklyQuest
from app.services.progress_service import ProgressService
from app.services.quest_service import QuestService, pick_quest, rotation, week_monday


async def _ctx(db, kid):
    today, tz = await ProgressService.family_today(db, kid.family_id)
    return today, tz, week_monday(today)


async def _template(db, family_id, *, bonus=False, active=True):
    t = TaskTemplate(id=uuid4(), title="Chore", points=10, interval_days=1,
                     assignment_type=AssignmentType.AUTO, is_bonus=bonus, is_active=active,
                     family_id=family_id)
    db.add(t)
    await db.commit()
    return t


async def _assign(db, kid, template, day, *, status=AssignmentStatus.COMPLETED, grade=None,
                  approval=ApprovalStatus.NONE, family_id=None):
    a = TaskAssignment(family_id=family_id or kid.family_id, template_id=template.id, assigned_to=kid.id,
                       status=status, approval_status=approval, completion_grade=grade,
                       assigned_date=day, week_of=day - timedelta(days=day.weekday()))
    db.add(a)
    await db.commit()
    return a


async def _quest(db, kid, week, quest, target, *, bonus=20):
    q = WeeklyQuest(family_id=kid.family_id, user_id=kid.id, week_start=week, quest=quest, target=target,
                    bonus_points=bonus, created_at=datetime.now(timezone.utc))
    db.add(q)
    await db.commit()
    await db.refresh(q)
    return q


async def _bonus_rows(db, kid):
    return list((await db.execute(
        select(PointTransaction).where(PointTransaction.user_id == kid.id, PointTransaction.type == PT.BONUS)
    )).scalars().all())


async def _quest_count(db, kid):
    return (await db.execute(
        select(func.count()).select_from(WeeklyQuest).where(WeeklyQuest.user_id == kid.id)
    )).scalar()


async def _gigs_off(db, family):
    family.enabled_modules = ["chat"]
    await db.commit()


class TestCreation:
    async def test_creates_one_quest_for_the_week_from_the_rotation(self, db_session, test_family, test_child_user):
        kid = test_child_user
        await _gigs_off(db_session, test_family)
        today, _tz, week = await _ctx(db_session, kid)
        chore = await _template(db_session, kid.family_id)
        for _ in range(3):
            await _assign(db_session, kid, chore, today, status=AssignmentStatus.PENDING)
        resp = await QuestService.sync(db_session, kid)
        expected = next(k for k in rotation(week, kid.id) if k in ("on_time", "perfect_days"))
        assert resp.applies is True and resp.quest is not None
        assert resp.quest.quest == expected
        assert resp.quest.target == (3 if expected == "on_time" else 1)
        assert resp.quest.progress == 0 and resp.quest.completed is False
        assert resp.quest.bonus_points == 20 and resp.quest.week_start == week
        assert resp.quest.days_left == 7 - today.weekday()
        assert resp.celebrate is None
        again = await QuestService.sync(db_session, kid)
        assert again.quest.id == resp.quest.id and await _quest_count(db_session, kid) == 1

    async def test_no_quest_until_something_qualifies_then_it_is_created(self, db_session, test_family, test_child_user):
        kid = test_child_user
        await _gigs_off(db_session, test_family)
        first = await QuestService.sync(db_session, kid)          # Monday 6 am: nothing assigned yet
        assert first.applies is True and first.quest is None and first.celebrate is None
        assert await _quest_count(db_session, kid) == 0
        today, _tz, _week = await _ctx(db_session, kid)
        chore = await _template(db_session, kid.family_id)
        await _assign(db_session, kid, chore, today, status=AssignmentStatus.PENDING)
        later = await QuestService.sync(db_session, kid)
        assert later.quest is not None and await _quest_count(db_session, kid) == 1

    async def test_the_goal_does_not_move_when_chores_are_added(self, db_session, test_family, test_child_user):
        kid = test_child_user
        await _gigs_off(db_session, test_family)
        today, _tz, _week = await _ctx(db_session, kid)
        chore = await _template(db_session, kid.family_id)
        for _ in range(3):
            await _assign(db_session, kid, chore, today, status=AssignmentStatus.PENDING)
        before = (await QuestService.sync(db_session, kid)).quest
        for _ in range(5):
            await _assign(db_session, kid, chore, today, status=AssignmentStatus.PENDING)
        after = (await QuestService.sync(db_session, kid)).quest
        assert (after.id, after.quest, after.target) == (before.id, before.quest, before.target)

    async def test_bonus_zero_switches_quests_off(self, db_session, test_family, test_child_user):
        kid = test_child_user
        today, _tz, _week = await _ctx(db_session, kid)
        await _assign(db_session, kid, await _template(db_session, kid.family_id), today,
                      status=AssignmentStatus.PENDING)
        test_family.quest_bonus_points = 0
        await db_session.commit()
        resp = await QuestService.sync(db_session, kid)
        assert resp.applies is False and resp.quest is None
        assert await _quest_count(db_session, kid) == 0

    async def test_parent_does_not_apply(self, db_session, test_parent_user):
        resp = await QuestService.sync(db_session, test_parent_user)
        assert resp.applies is False and resp.quest is None and resp.celebrate is None

    async def test_history_counts_the_previous_four_weeks_only(self, db_session, test_child_user):
        kid = test_child_user
        today, tz, week = await _ctx(db_session, kid)
        chore = await _template(db_session, kid.family_id)
        last_week = week - timedelta(days=7)
        for i in range(5):
            await _assign(db_session, kid, chore, last_week + timedelta(days=i))
        await _assign(db_session, kid, chore, last_week + timedelta(days=5), status=AssignmentStatus.OVERDUE)
        for i in range(3):
            await _assign(db_session, kid, chore, week - timedelta(days=42 + i))     # six weeks back
        await _assign(db_session, kid, chore, today)                                  # this week: not history
        history = await QuestService._history(db_session, kid.family_id, kid.id, week, tz, today)
        assert history["on_time"] == 5 and history["perfect_days"] == 5

    async def test_open_gigs_counts_what_the_kid_could_still_get_approved(
        self, db_session, test_family, test_child_user, test_teen_user,
    ):
        fid, child, teen = test_family.id, test_child_user, test_teen_user

        async def open_for(kid, *, star=False, modules=None):
            return await QuestService._open_gigs(db_session, fid, kid.id, kid.role, star, modules)

        assert await open_for(child) == 0                                          # no offerings
        db_session.add(GigOffering(family_id=fid, title="Teens only", points=50, allowed_roles=["teen"]))
        await db_session.commit()
        assert await open_for(child) == 0 and await open_for(teen) == 1
        anyone = GigOffering(family_id=fid, title="Anyone", points=20)
        other = Family(name="Other")
        db_session.add_all([
            anyone, other,
            GigOffering(family_id=fid, title="Closed", points=20, is_active=False),
            GigOffering(family_id=fid, title="Proposal", points=20, status=GigOfferingStatus.PENDING.value),
        ])
        await db_session.commit()
        db_session.add(GigOffering(family_id=other.id, title="Not ours", points=20))
        await db_session.commit()
        assert await open_for(child) == 1 and await open_for(teen) == 2            # open to all: counted
        # the kid already holds an approved claim on a multi-slot gig: nothing left to get there
        done = GigOffering(family_id=fid, title="Done", points=20, allow_multiple=True)
        db_session.add(done)
        await db_session.commit()
        db_session.add(GigClaim(gig_id=done.id, family_id=fid, claimed_by=child.id,
                                status=GigClaimStatus.APPROVED, approved_at=datetime.now(timezone.utc)))
        # a claim still awaiting approval can still be approved: counted
        db_session.add(GigClaim(gig_id=anyone.id, family_id=fid, claimed_by=child.id,
                                status=GigClaimStatus.COMPLETED))
        await db_session.commit()
        assert await open_for(child) == 1
        assert await open_for(teen) == 3                                           # the child's claim is not the teen's
        # star-mode kids have no gig board; a family with gigs off has none either
        assert await open_for(child, star=True) == 0
        assert await open_for(child, modules=["chat"]) == 0

    async def test_extra_mile_is_sized_from_the_bonus_tasks_on_the_board(self, db_session, test_child_user):
        kid = test_child_user
        today, tz, week = await _ctx(db_session, kid)
        bonus = await _template(db_session, kid.family_id, bonus=True)
        for weeks_back in range(1, 5):                                             # one a week: avg 1, stretch 2
            await _assign(db_session, kid, bonus, week - timedelta(weeks=weeks_back),
                          approval=ApprovalStatus.APPROVED)
        await _assign(db_session, kid, bonus, today, status=AssignmentStatus.PENDING)   # ONE open this week
        stats = await QuestService.stats_for(db_session, kid.family_id, kid.id, week, tz, today)
        history = await QuestService._history(db_session, kid.family_id, kid.id, week, tz, today)
        assert history["extra_mile"] == 4
        assert pick_quest(["extra_mile", "on_time", "perfect_days", "go_getter"], stats, history, 0) == ("extra_mile", 1)


class TestProgressAndPayment:
    async def test_on_time_counts_strictly_and_pays_when_the_goal_is_reached(self, db_session, test_child_user):
        kid = test_child_user
        today, _tz, week = await _ctx(db_session, kid)
        chore = await _template(db_session, kid.family_id)
        quest = await _quest(db_session, kid, week, "on_time", 2)
        await _assign(db_session, kid, chore, today)                                           # counts
        waiting = await _assign(db_session, kid, chore, today, approval=ApprovalStatus.PENDING)
        await _assign(db_session, kid, chore, today, approval=ApprovalStatus.REJECTED)
        await _assign(db_session, kid, chore, today, grade="missed")
        points_before = kid.points
        resp = await QuestService.sync(db_session, kid)
        assert resp.quest.id == quest.id and resp.quest.progress == 1 and resp.quest.completed is False
        assert resp.celebrate is None and await _bonus_rows(db_session, kid) == []
        await db_session.execute(                                                              # the parent approves
            update(TaskAssignment).where(TaskAssignment.id == waiting.id).values(approval_status=ApprovalStatus.APPROVED)
        )
        await db_session.commit()
        resp = await QuestService.sync(db_session, kid)
        assert resp.quest.progress == 2 and resp.quest.completed is True
        assert resp.celebrate is not None and resp.celebrate.id == quest.id and resp.celebrate.last_week is False
        assert resp.celebrate.bonus_points == 20
        rows = await _bonus_rows(db_session, kid)
        assert len(rows) == 1 and rows[0].points == 20 and rows[0].family_id == kid.family_id
        assert rows[0].balance_before == points_before and rows[0].balance_after == points_before + 20
        await db_session.refresh(kid)
        assert kid.points == points_before + 20

    async def test_the_bonus_is_paid_once_across_many_reads(self, db_session, test_child_user):
        kid = test_child_user
        today, _tz, week = await _ctx(db_session, kid)
        await _quest(db_session, kid, week, "on_time", 1)
        await _assign(db_session, kid, await _template(db_session, kid.family_id), today)
        points_before = kid.points
        for _ in range(3):
            resp = await QuestService.sync(db_session, kid)
        assert resp.quest.completed is True and resp.quest.progress == 1
        assert len(await _bonus_rows(db_session, kid)) == 1
        await db_session.refresh(kid)
        assert kid.points == points_before + 20

    async def test_the_bonus_is_added_to_the_current_balance_not_a_stale_one(self, db_session, test_child_user):
        kid = test_child_user
        today, _tz, week = await _ctx(db_session, kid)
        await _quest(db_session, kid, week, "on_time", 1)
        await _assign(db_session, kid, await _template(db_session, kid.family_id), today)
        # Simulate a balance change committed by someone else (another tab, a
        # parent approval) while `kid` stays loaded in this session's identity
        # map — `expire_on_commit=False` means nothing refreshes it for us.
        await db_session.execute(
            update(User).where(User.id == kid.id).values(points=175).execution_options(synchronize_session=False)
        )
        await db_session.commit()
        assert kid.points == 100                                    # proves the in-memory copy is stale
        await QuestService.sync(db_session, kid)
        rows = await _bonus_rows(db_session, kid)
        assert len(rows) == 1
        assert rows[0].balance_before == 175 and rows[0].balance_after == 195
        await db_session.refresh(kid)
        assert kid.points == 195

    async def test_settle_twice_pays_once(self, db_session, test_child_user):
        kid = test_child_user
        _today, _tz, week = await _ctx(db_session, kid)
        quest = await _quest(db_session, kid, week, "on_time", 1)
        await QuestService._settle(db_session, quest, "en")
        await QuestService._settle(db_session, quest, "en")
        assert len(await _bonus_rows(db_session, kid)) == 1 and quest.rewarded_at is not None

    async def test_the_bonus_is_the_amount_fixed_at_creation(self, db_session, test_family, test_child_user):
        kid = test_child_user
        today, _tz, week = await _ctx(db_session, kid)
        await _quest(db_session, kid, week, "on_time", 1, bonus=20)
        test_family.quest_bonus_points = 50
        await db_session.commit()
        await _assign(db_session, kid, await _template(db_session, kid.family_id), today)
        await QuestService.sync(db_session, kid)
        assert [r.points for r in await _bonus_rows(db_session, kid)] == [20]

    async def test_bonus_zero_stops_an_in_flight_quest(self, db_session, test_family, test_child_user):
        kid = test_child_user
        today, _tz, week = await _ctx(db_session, kid)
        quest = await _quest(db_session, kid, week, "on_time", 1)
        await _assign(db_session, kid, await _template(db_session, kid.family_id), today)
        test_family.quest_bonus_points = 0
        await db_session.commit()
        resp = await QuestService.sync(db_session, kid)
        assert resp.applies is False
        await db_session.refresh(quest)
        assert quest.rewarded_at is None and await _bonus_rows(db_session, kid) == []

    async def test_last_weeks_quest_is_paid_on_this_weeks_read(self, db_session, test_child_user):
        kid = test_child_user
        _today, _tz, week = await _ctx(db_session, kid)
        chore = await _template(db_session, kid.family_id)
        last_week = week - timedelta(days=7)
        older_week = week - timedelta(days=14)
        last = await _quest(db_session, kid, last_week, "on_time", 1)
        older = await _quest(db_session, kid, older_week, "on_time", 1)
        await _assign(db_session, kid, chore, last_week)       # Sunday-night finish / late approval
        await _assign(db_session, kid, chore, older_week)
        resp = await QuestService.sync(db_session, kid)
        assert resp.celebrate is not None and resp.celebrate.id == last.id and resp.celebrate.last_week is True
        assert len(await _bonus_rows(db_session, kid)) == 1
        await db_session.refresh(older)
        assert older.rewarded_at is None                       # two weeks back is never settled

    async def test_extra_mile_counts_bonus_tasks_that_count(self, db_session, test_child_user):
        kid = test_child_user
        today, _tz, week = await _ctx(db_session, kid)
        bonus = await _template(db_session, kid.family_id, bonus=True)
        await _quest(db_session, kid, week, "extra_mile", 2)
        await _assign(db_session, kid, bonus, today, approval=ApprovalStatus.APPROVED)
        await _assign(db_session, kid, bonus, today, approval=ApprovalStatus.PENDING)
        await _assign(db_session, kid, await _template(db_session, kid.family_id), today)   # a chore, not a bonus
        resp = await QuestService.sync(db_session, kid)
        assert resp.quest.quest == "extra_mile" and resp.quest.progress == 1

    async def test_go_getter_counts_gigs_approved_this_week(self, db_session, test_child_user):
        kid = test_child_user
        _today, _tz, week = await _ctx(db_session, kid)
        await _quest(db_session, kid, week, "go_getter", 2)
        gigs = [GigOffering(family_id=kid.family_id, title=f"Gig {i}", points=30) for i in range(3)]
        db_session.add_all(gigs)
        await db_session.commit()
        now = datetime.now(timezone.utc)
        db_session.add_all([
            GigClaim(gig_id=gigs[0].id, family_id=kid.family_id, claimed_by=kid.id,
                     status=GigClaimStatus.APPROVED, approved_at=now),
            GigClaim(gig_id=gigs[1].id, family_id=kid.family_id, claimed_by=kid.id,
                     status=GigClaimStatus.APPROVED, approved_at=now - timedelta(days=8)),
            GigClaim(gig_id=gigs[2].id, family_id=kid.family_id, claimed_by=kid.id,
                     status=GigClaimStatus.COMPLETED),
        ])
        await db_session.commit()
        resp = await QuestService.sync(db_session, kid)
        assert resp.quest.quest == "go_getter" and resp.quest.progress == 1

    async def test_perfect_days_needs_every_chore_of_the_day(self, db_session, test_child_user):
        kid = test_child_user
        today, _tz, week = await _ctx(db_session, kid)
        chore = await _template(db_session, kid.family_id)
        await _quest(db_session, kid, week, "perfect_days", 1)
        await _assign(db_session, kid, chore, today)
        open_one = await _assign(db_session, kid, chore, today, status=AssignmentStatus.PENDING)
        assert (await QuestService.sync(db_session, kid)).quest.progress == 0
        await db_session.execute(
            update(TaskAssignment).where(TaskAssignment.id == open_one.id).values(status=AssignmentStatus.COMPLETED)
        )
        await db_session.commit()
        resp = await QuestService.sync(db_session, kid)
        assert resp.quest.progress == 1 and resp.quest.completed is True

    async def test_a_siblings_and_another_familys_work_never_counts(self, db_session, test_child_user, test_teen_user):
        kid = test_child_user
        today, _tz, week = await _ctx(db_session, kid)
        chore = await _template(db_session, kid.family_id)
        bonus = await _template(db_session, kid.family_id, bonus=True)
        await _quest(db_session, kid, week, "on_time", 1)
        await _assign(db_session, test_teen_user, chore, today)                       # sibling's chore
        await _assign(db_session, test_teen_user, bonus, today, approval=ApprovalStatus.APPROVED)
        other = Family(name="Other")
        db_session.add(other)
        await db_session.commit()
        await _assign(db_session, kid, await _template(db_session, other.id), today, family_id=other.id)
        resp = await QuestService.sync(db_session, kid)
        assert resp.quest.progress == 0 and resp.quest.completed is False
        stats = await QuestService.stats_for(db_session, kid.family_id, kid.id, week, _tz, today)
        assert stats.done == {"on_time": 0, "perfect_days": 0, "extra_mile": 0, "go_getter": 0}
        assert await _bonus_rows(db_session, kid) == []


class TestAckAndHub:
    async def _paid(self, db, kid):
        today, _tz, week = await _ctx(db, kid)
        quest = await _quest(db, kid, week, "on_time", 1)
        await _assign(db, kid, await _template(db, kid.family_id), today)
        await QuestService.sync(db, kid)
        return quest

    async def test_ack_marks_the_done_moment_seen(self, db_session, test_child_user):
        quest = await self._paid(db_session, test_child_user)
        assert (await QuestService.sync(db_session, test_child_user)).celebrate.id == quest.id
        await QuestService.ack(db_session, test_child_user, quest.id)
        resp = await QuestService.sync(db_session, test_child_user)
        assert resp.celebrate is None and resp.quest.completed is True and resp.quest.progress == resp.quest.target

    async def test_ack_ignores_someone_elses_quest(self, db_session, test_child_user, test_teen_user):
        quest = await self._paid(db_session, test_child_user)
        await QuestService.ack(db_session, test_teen_user, quest.id)
        assert (await QuestService.sync(db_session, test_child_user)).celebrate is not None

    async def test_hub_progress_reads_without_creating_or_paying(self, db_session, test_family,
                                                                 test_child_user, test_teen_user):
        kid = test_child_user
        today, _tz, week = await _ctx(db_session, kid)
        chore = await _template(db_session, kid.family_id)
        await _quest(db_session, kid, week, "on_time", 2)
        await _assign(db_session, kid, chore, today)
        await _assign(db_session, test_teen_user, chore, today, status=AssignmentStatus.PENDING)   # teen has no quest row
        ids = [kid.id, test_teen_user.id]
        hub = await QuestService.hub_progress(db_session, test_family.id, ids)
        assert hub == {kid.id: (1, 2, False)}
        assert await _quest_count(db_session, test_teen_user) == 0
        await _assign(db_session, kid, chore, today)                    # goal reached, but the hub never pays
        hub = await QuestService.hub_progress(db_session, test_family.id, ids)
        assert hub == {kid.id: (2, 2, False)} and await _bonus_rows(db_session, kid) == []
        test_family.quest_bonus_points = 0
        await db_session.commit()
        assert await QuestService.hub_progress(db_session, test_family.id, ids) == {}
