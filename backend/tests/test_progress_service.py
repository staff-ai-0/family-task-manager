"""UX-D1 progress queries against the test DB (family-scoped, tz-aware)."""
from datetime import datetime, time, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select, update

from app.models.cash_transaction import CashTransaction, CashTransactionType as CT
from app.models.family import Family
from app.models.point_transaction import PointTransaction, TransactionType as PT
from app.models.task_assignment import ApprovalStatus, AssignmentStatus, TaskAssignment
from app.models.task_template import AssignmentType, TaskTemplate
from app.models.user import User
from app.services.progress_service import DayState as S, ProgressService


async def _pt(db, kid, typ, points):
    db.add(PointTransaction(type=typ, points=points, user_id=kid.id, family_id=kid.family_id,
                            balance_before=0, balance_after=max(points, 0)))
    await db.commit()


async def _ct(db, kid, typ, cents):
    db.add(CashTransaction(type=typ, amount_cents=cents, user_id=kid.id, family_id=kid.family_id,
                           balance_before=0, balance_after=max(cents, 0)))
    await db.commit()


async def _template(db, family_id, *, bonus=False):
    t = TaskTemplate(id=uuid4(), title="Chore", points=10, interval_days=1,
                     assignment_type=AssignmentType.AUTO, is_bonus=bonus, is_active=True,
                     family_id=family_id)
    db.add(t)
    await db.commit()
    return t


async def _assign(db, kid, template, day, *, status=AssignmentStatus.COMPLETED, completed_at=None,
                  grade=None, approval=ApprovalStatus.NONE):
    a = TaskAssignment(family_id=kid.family_id, template_id=template.id, assigned_to=kid.id,
                       status=status, approval_status=approval, completion_grade=grade,
                       assigned_date=day, week_of=day - timedelta(days=day.weekday()),
                       completed_at=completed_at)
    db.add(a)
    await db.commit()
    return a


def _at(day, hour, tz):
    return datetime.combine(day, time(hour, 0), tzinfo=tz).astimezone(timezone.utc)


class TestXp:
    async def test_counts_only_earning_types(self, db_session, test_child_user):
        kid = test_child_user
        await _pt(db_session, kid, PT.TASK_COMPLETED, 40)
        await _pt(db_session, kid, PT.BONUS, 10)
        await _pt(db_session, kid, PT.GIG_APPROVED, 5)
        await _pt(db_session, kid, PT.PARENT_ADJUSTMENT, 500)
        await _pt(db_session, kid, PT.REWARD_REDEEMED, -30)
        await _pt(db_session, kid, PT.PENALTY, -20)
        await _ct(db_session, kid, CT.GIG_EARNED, 8050)    # $80.50 -> 80 XP
        await _ct(db_session, kid, CT.ALLOWANCE, 5000)
        await _ct(db_session, kid, CT.PAYOUT, -2000)
        xp = await ProgressService.xp_for(db_session, kid.family_id, kid.id)
        assert xp == 40 + 10 + 5 + 80
        assert isinstance(xp, int)

    async def test_another_familys_rows_never_count(self, db_session, test_child_user):
        other = Family(name="Other")
        db_session.add(other)
        await db_session.commit()
        db_session.add(PointTransaction(type=PT.TASK_COMPLETED, points=999, user_id=test_child_user.id,
                                        family_id=other.id, balance_before=0, balance_after=999))
        await db_session.commit()
        assert await ProgressService.xp_for(db_session, test_child_user.family_id, test_child_user.id) == 0

    async def test_split_gig_pay_sums_before_flooring(self, db_session, test_child_user):
        """F1: CashService.credit_split_rows writes one gig_earned row per jar
        (save/share/spend), each possibly under a dollar. Flooring PER ROW
        (3 + 1 + 0 = 4) undercounts a $5 gig split 350/100/50 cents; flooring
        AFTER summing (500 // 100 = 5) is correct."""
        kid = test_child_user
        await _ct(db_session, kid, CT.GIG_EARNED, 350)
        await _ct(db_session, kid, CT.GIG_EARNED, 100)
        await _ct(db_session, kid, CT.GIG_EARNED, 50)
        assert await ProgressService.xp_for(db_session, kid.family_id, kid.id) == 5

    async def test_reopen_correction_nets_points_not_discarded(self, db_session, test_child_user):
        """F2: patch_assignment's reopen claw-back writes a negative
        TASK_COMPLETED row. The old `points > 0` filter discarded it, so a
        reopen+redo double-counted the original award."""
        kid = test_child_user
        await _pt(db_session, kid, PT.TASK_COMPLETED, 40)
        await _pt(db_session, kid, PT.TASK_COMPLETED, -40)  # reopen claws back
        await _pt(db_session, kid, PT.TASK_COMPLETED, 40)   # redone
        assert await ProgressService.xp_for(db_session, kid.family_id, kid.id) == 40

    async def test_collaboration_resplit_nets_points_for_first_kid(self, db_session, test_child_user, test_teen_user):
        """F2: _settle_collaboration's re-split writes a negative GIG_APPROVED
        delta on the original completer when a sibling joins. The first
        kid's net share must reflect the claw-back, not the original award."""
        kid, sibling = test_child_user, test_teen_user
        await _pt(db_session, kid, PT.GIG_APPROVED, 30)
        await _pt(db_session, kid, PT.GIG_APPROVED, -15)     # re-split claws back half
        await _pt(db_session, sibling, PT.GIG_APPROVED, 15)  # sibling's new share
        assert await ProgressService.xp_for(db_session, kid.family_id, kid.id) == 15
        assert await ProgressService.xp_for(db_session, kid.family_id, sibling.id) == 15

    async def test_net_points_cannot_go_below_zero(self, db_session, test_child_user):
        kid = test_child_user
        await _pt(db_session, kid, PT.TASK_COMPLETED, -10)  # a lone correction row
        assert await ProgressService.xp_for(db_session, kid.family_id, kid.id) == 0

    async def test_net_cash_cannot_go_below_zero(self, db_session, test_child_user):
        kid = test_child_user
        await _ct(db_session, kid, CT.GIG_EARNED, -500)  # a lone claw-back row
        assert await ProgressService.xp_for(db_session, kid.family_id, kid.id) == 0


class TestDayStates:
    async def test_done_missed_none_and_bonus_ignored(self, db_session, test_family, test_child_user):
        kid = test_child_user
        today, tz = await ProgressService.family_today(db_session, test_family.id)
        chore = await _template(db_session, test_family.id)
        bonus = await _template(db_session, test_family.id, bonus=True)
        y = today - timedelta(days=1)
        await _assign(db_session, kid, chore, y, completed_at=_at(y, 18, tz))
        await _assign(db_session, kid, bonus, y, status=AssignmentStatus.PENDING)  # bonus: ignored
        d2 = today - timedelta(days=2)
        await _assign(db_session, kid, chore, d2, completed_at=_at(d2, 9, tz))
        await _assign(db_session, kid, chore, d2, status=AssignmentStatus.OVERDUE)  # one open -> missed
        d4 = today - timedelta(days=4)
        await _assign(db_session, kid, chore, d4, status=AssignmentStatus.CANCELLED)  # cancelled only -> none
        states = await ProgressService.day_states(db_session, test_family.id, kid.id, today, tz)
        assert states[y] == S.done
        assert states[d2] == S.missed
        assert states.get(d4, S.none) == S.none
        assert states.get(today - timedelta(days=3), S.none) == S.none

    async def test_missed_grade_and_rejection_count_as_missed(self, db_session, test_family, test_child_user):
        kid = test_child_user
        today, tz = await ProgressService.family_today(db_session, test_family.id)
        chore = await _template(db_session, test_family.id)
        y, d2 = today - timedelta(days=1), today - timedelta(days=2)
        await _assign(db_session, kid, chore, y, completed_at=_at(y, 10, tz), grade="missed")
        await _assign(db_session, kid, chore, d2, completed_at=_at(d2, 10, tz), approval=ApprovalStatus.REJECTED)
        states = await ProgressService.day_states(db_session, test_family.id, kid.id, today, tz)
        assert states[y] == S.missed and states[d2] == S.missed

    async def test_completed_after_its_day_is_missed(self, db_session, test_family, test_child_user):
        kid = test_child_user
        today, tz = await ProgressService.family_today(db_session, test_family.id)
        chore = await _template(db_session, test_family.id)
        d2 = today - timedelta(days=2)
        await _assign(db_session, kid, chore, d2, completed_at=_at(today - timedelta(days=1), 10, tz))
        states = await ProgressService.day_states(db_session, test_family.id, kid.id, today, tz)
        assert states[d2] == S.missed

    async def test_completion_late_evening_local_counts_for_that_day(self, db_session, test_family, test_child_user):
        test_family.timezone = "America/Mexico_City"
        await db_session.commit()
        kid = test_child_user
        today, tz = await ProgressService.family_today(db_session, test_family.id)
        chore = await _template(db_session, test_family.id)
        y = today - timedelta(days=1)
        await _assign(db_session, kid, chore, y, completed_at=_at(y, 23, tz))  # next day in UTC
        states = await ProgressService.day_states(db_session, test_family.id, kid.id, today, tz)
        assert states[y] == S.done

    async def test_legacy_completed_without_timestamp_counts_done(self, db_session, test_family, test_child_user):
        kid = test_child_user
        today, tz = await ProgressService.family_today(db_session, test_family.id)
        chore = await _template(db_session, test_family.id)
        y = today - timedelta(days=1)
        await _assign(db_session, kid, chore, y, completed_at=None)  # status COMPLETED, no timestamp
        states = await ProgressService.day_states(db_session, test_family.id, kid.id, today, tz)
        assert states[y] == S.done

    async def test_partial_grade_counts_as_done(self, db_session, test_family, test_child_user):
        """Only `missed` excludes a day — `partial` (a graded-down but still
        approved completion) completed on its own day still counts done."""
        kid = test_child_user
        today, tz = await ProgressService.family_today(db_session, test_family.id)
        chore = await _template(db_session, test_family.id)
        y = today - timedelta(days=1)
        await _assign(db_session, kid, chore, y, completed_at=_at(y, 18, tz), grade="partial")
        states = await ProgressService.day_states(db_session, test_family.id, kid.id, today, tz)
        assert states[y] == S.done

    async def test_today_done_vs_open(self, db_session, test_family, test_child_user):
        kid = test_child_user
        today, tz = await ProgressService.family_today(db_session, test_family.id)
        chore = await _template(db_session, test_family.id)
        await _assign(db_session, kid, chore, today, status=AssignmentStatus.PENDING)
        states = await ProgressService.day_states(db_session, test_family.id, kid.id, today, tz)
        assert states[today] == S.today


class TestProgressFor:
    async def test_parent_does_not_apply(self, db_session, test_parent_user):
        r = await ProgressService.progress_for(db_session, test_parent_user)
        assert r.applies is False

    async def test_kid_xp_rank_streak_and_celebrate(self, db_session, test_family, test_child_user):
        kid = test_child_user
        await _pt(db_session, kid, PT.TASK_COMPLETED, 350)   # rank 3
        today, tz = await ProgressService.family_today(db_session, test_family.id)
        chore = await _template(db_session, test_family.id)
        y = today - timedelta(days=1)
        await _assign(db_session, kid, chore, y, completed_at=_at(y, 12, tz))
        r = await ProgressService.progress_for(db_session, kid)
        assert r.applies and r.xp == 350 and r.rank == 3
        assert r.rank_floor_xp == 300 and r.next_rank_xp == 600
        assert r.streak_days == 1
        assert len(r.week) == 7
        assert r.celebrate_rank == 3        # never seen a celebration
        kid.last_seen_rank = 3
        await db_session.commit()
        r2 = await ProgressService.progress_for(db_session, kid)
        assert r2.celebrate_rank is None

    async def test_rank_one_never_celebrates(self, db_session, test_child_user):
        r = await ProgressService.progress_for(db_session, test_child_user)
        assert r.rank == 1 and r.celebrate_rank is None


class TestAckRank:
    """Controller ruling T3-2: ack_rank must be a single atomic UPDATE, never
    a read-modify-write on a (possibly stale, e.g. two-tab) in-memory ORM
    object — otherwise a late commit of a stale read can LOWER
    last_seen_rank, breaking the "only moves up" invariant."""

    async def test_stale_in_memory_user_cannot_lower_stored_value(self, db_session, test_child_user):
        kid = test_child_user
        await _pt(db_session, kid, PT.TASK_COMPLETED, 650)  # rank 4

        # Simulate "tab A already holds last_seen_rank=4 in the DB" without
        # ever refreshing `kid` — its in-memory last_seen_rank stays None,
        # exactly like a second stale in-memory User object would after a
        # concurrent request already committed the rank-4 ack.
        await db_session.execute(
            update(User)
            .where(User.id == kid.id)
            .values(last_seen_rank=4)
            .execution_options(synchronize_session=False)
        )
        await db_session.commit()
        assert kid.last_seen_rank is None  # confirms the staleness this test relies on

        # "Tab B" acks a lower rank (2) using the stale in-memory object.
        await ProgressService.ack_rank(db_session, kid, 2)

        stored = (
            await db_session.execute(select(User.last_seen_rank).where(User.id == kid.id))
        ).scalar_one()
        assert stored == 4  # must NOT have been lowered to 2

    async def test_ack_raises_from_none_and_never_exceeds_held_rank(self, db_session, test_child_user):
        kid = test_child_user
        await _pt(db_session, kid, PT.TASK_COMPLETED, 650)  # rank 4

        await ProgressService.ack_rank(db_session, kid, 4)
        stored = (
            await db_session.execute(select(User.last_seen_rank).where(User.id == kid.id))
        ).scalar_one()
        assert stored == 4  # raised from NULL

        await ProgressService.ack_rank(db_session, kid, 9)  # clamped to held rank
        stored2 = (
            await db_session.execute(select(User.last_seen_rank).where(User.id == kid.id))
        ).scalar_one()
        assert stored2 == 4  # never above the held rank
