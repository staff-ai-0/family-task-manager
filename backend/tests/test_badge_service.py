"""UX-D2 badge counts, awarding and acks against the test DB (family-scoped)."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import func, select, update

from app.models.family import Family
from app.models.family_cup import FamilyCupSeason
from app.models.gig import GigClaim, GigClaimStatus, GigOffering
from app.models.kid_savings_goal import GOAL_ACTIVE, GOAL_CANCELLED, KidSavingsGoal
from app.models.point_transaction import PointTransaction, TransactionType as PT
from app.models.task_assignment import ApprovalStatus, AssignmentStatus, TaskAssignment
from app.models.task_template import AssignmentType, TaskTemplate
from app.models.user_badge import UserBadge
from app.services.badge_service import BADGES, BadgeService
from app.services.progress_service import ProgressService


async def _template(db, family_id, *, bonus=False):
    t = TaskTemplate(id=uuid4(), title="Chore", points=10, interval_days=1,
                     assignment_type=AssignmentType.AUTO, is_bonus=bonus, is_active=True,
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


async def _today(db, kid):
    today, _ = await ProgressService.family_today(db, kid.family_id)
    return today


async def _chores(db, kid, n, *, start_days_ago=400):
    """n completed chores on distinct days OUTSIDE the 365-day streak window,
    so they move the chores count without touching streak / perfect week."""
    template = await _template(db, kid.family_id)
    today = await _today(db, kid)
    rows = []
    for i in range(n):
        rows.append(await _assign(db, kid, template, today - timedelta(days=start_days_ago + i)))
    return rows


async def _cup(db, kid, weeks_ago, *, family_id=None):
    today = await _today(db, kid)
    monday = today - timedelta(days=today.weekday())
    db.add(FamilyCupSeason(family_id=family_id or kid.family_id,
                           week_start=monday - timedelta(weeks=weeks_ago),
                           winner_user_id=kid.id, winner_name=kid.name, winner_points=10))
    await db.commit()


def _b(resp, key):
    return next(b for b in resp.badges if b.badge == key)


async def _stored(db, kid):
    return (await db.execute(select(func.count()).select_from(UserBadge).where(UserBadge.user_id == kid.id))).scalar()


class TestCounts:
    async def test_new_kid_has_every_family_at_tier_zero(self, db_session, test_child_user):
        resp = await BadgeService.sync(db_session, test_child_user)
        assert resp.applies is True
        assert [b.badge for b in resp.badges] == list(BADGES)
        assert all(b.tier == 0 and b.count == 0 and b.earned_at is None for b in resp.badges)
        assert [b.next_target for b in resp.badges] == [BADGES[k].thresholds[0] for k in BADGES]
        assert resp.unseen == [] and resp.earned_total == 0
        assert await _stored(db_session, test_child_user) == 0

    async def test_parent_does_not_apply(self, db_session, test_parent_user):
        resp = await BadgeService.sync(db_session, test_parent_user)
        assert resp.applies is False and resp.badges == [] and resp.unseen == []

    async def test_chores_and_extra_mile_follow_the_done_rule(self, db_session, test_child_user):
        kid = test_child_user
        today = await _today(db_session, kid)
        chore = await _template(db_session, kid.family_id)
        bonus = await _template(db_session, kid.family_id, bonus=True)
        old = today - timedelta(days=400)
        for i in range(10):
            await _assign(db_session, kid, chore, old - timedelta(days=i))
        await _assign(db_session, kid, chore, old - timedelta(days=20), grade="missed")
        await _assign(db_session, kid, chore, old - timedelta(days=21), approval=ApprovalStatus.REJECTED)
        await _assign(db_session, kid, chore, old - timedelta(days=22), status=AssignmentStatus.PENDING)
        await _assign(db_session, kid, chore, old - timedelta(days=23), status=AssignmentStatus.CANCELLED)
        await _assign(db_session, kid, bonus, old - timedelta(days=24))
        # Awaiting parent review: not counted yet (a badge is permanent, a
        # later rejection could not take it back). Approved: counted.
        await _assign(db_session, kid, chore, old - timedelta(days=25), approval=ApprovalStatus.PENDING)
        await _assign(db_session, kid, bonus, old - timedelta(days=26), approval=ApprovalStatus.PENDING)
        await _assign(db_session, kid, chore, old - timedelta(days=27), approval=ApprovalStatus.APPROVED)
        resp = await BadgeService.sync(db_session, kid)
        assert _b(resp, "chores").count == 11 and _b(resp, "chores").tier == 1
        assert _b(resp, "chores").next_target == 50
        assert _b(resp, "extra_mile").count == 1 and _b(resp, "extra_mile").tier == 1
        assert isinstance(_b(resp, "chores").count, int)

    async def test_gigs_saver_rewards_and_cup(self, db_session, test_child_user, test_teen_user, test_reward):
        kid = test_child_user
        gig = GigOffering(family_id=kid.family_id, title="Wash the car", points=50)
        gig2 = GigOffering(family_id=kid.family_id, title="Mow the lawn", points=80)
        db_session.add_all([gig, gig2])
        await db_session.commit()
        db_session.add_all([
            GigClaim(gig_id=gig.id, family_id=kid.family_id, claimed_by=kid.id, status=GigClaimStatus.APPROVED),
            GigClaim(gig_id=gig2.id, family_id=kid.family_id, claimed_by=kid.id, status=GigClaimStatus.REJECTED),
            KidSavingsGoal(family_id=kid.family_id, user_id=kid.id, name="Bici", target_cents=50000,
                           status=GOAL_CANCELLED, reached_at=datetime.now(timezone.utc)),
            KidSavingsGoal(family_id=kid.family_id, user_id=kid.id, name="Switch", target_cents=900000,
                           status=GOAL_ACTIVE),
            # A real reward redemption...
            PointTransaction(type=PT.REWARD_REDEEMED, points=-100, user_id=kid.id, family_id=kid.family_id,
                             reward_id=test_reward.id, balance_before=100, balance_after=0),
            # ...and a pet-shop purchase, which writes the same type with no reward_id.
            PointTransaction(type=PT.REWARD_REDEEMED, points=-20, user_id=kid.id, family_id=kid.family_id,
                             balance_before=20, balance_after=0),
        ])
        await db_session.commit()
        await _cup(db_session, kid, 1)
        await _cup(db_session, test_teen_user, 2)      # someone else's win
        resp = await BadgeService.sync(db_session, kid)
        for key in ("gigs", "saver", "rewards", "cup"):
            assert _b(resp, key).count == 1, key
            assert _b(resp, key).tier == 1, key

    async def test_streak_and_perfect_week_come_from_the_day_walk(self, db_session, test_child_user):
        kid = test_child_user
        today = await _today(db_session, kid)
        chore = await _template(db_session, kid.family_id)
        last_monday = today - timedelta(days=today.weekday() + 7)
        for i in range(7):                              # last week, Mon..Sun, all done on time
            await _assign(db_session, kid, chore, last_monday + timedelta(days=i))
        resp = await BadgeService.sync(db_session, kid)
        assert _b(resp, "streak").count == 7 and _b(resp, "streak").tier == 1
        assert _b(resp, "perfect_week").count == 1 and _b(resp, "perfect_week").tier == 1
        assert _b(resp, "chores").count == 7 and _b(resp, "chores").tier == 0

    async def test_another_familys_rows_never_count(self, db_session, test_child_user, test_reward):
        kid = test_child_user
        other = Family(name="Other")
        db_session.add(other)
        await db_session.commit()
        chore = await _template(db_session, other.id)
        today = await _today(db_session, kid)
        for i in range(10):
            await _assign(db_session, kid, chore, today - timedelta(days=400 + i), family_id=other.id)
        await _cup(db_session, kid, 1, family_id=other.id)
        db_session.add(PointTransaction(type=PT.REWARD_REDEEMED, points=-100, user_id=kid.id, family_id=other.id,
                                        reward_id=test_reward.id, balance_before=100, balance_after=0))
        await db_session.commit()
        resp = await BadgeService.sync(db_session, kid)
        assert all(b.count == 0 and b.tier == 0 for b in resp.badges)


class TestAwarding:
    async def test_backfill_awards_every_crossed_tier_once_and_ack_clears_them(self, db_session, test_child_user):
        kid = test_child_user
        await _chores(db_session, kid, 60)                       # bronze (10) and silver (50) at once
        resp = await BadgeService.sync(db_session, kid)
        assert _b(resp, "chores").tier == 2 and _b(resp, "chores").next_target == 200
        assert [(u.badge, u.tier) for u in resp.unseen] == [("chores", 1), ("chores", 2)]
        assert resp.earned_total == 2
        again = await BadgeService.sync(db_session, kid)         # second visit: nothing new
        assert await _stored(db_session, kid) == 2
        assert len(again.unseen) == 2                            # still unseen until acked
        await BadgeService.ack(db_session, kid, [u.id for u in again.unseen])
        after = await BadgeService.sync(db_session, kid)
        assert after.unseen == [] and after.earned_total == 2 and _b(after, "chores").tier == 2

    async def test_award_twice_is_a_no_op_not_an_error(self, db_session, test_child_user):
        kid = test_child_user
        await BadgeService._award(db_session, kid.family_id, kid.id, [("cup", 1)])
        await BadgeService._award(db_session, kid.family_id, kid.id, [("cup", 1), ("cup", 2)])
        assert await _stored(db_session, kid) == 2

    async def test_earned_tier_survives_the_count_dropping(self, db_session, test_child_user):
        kid = test_child_user
        rows = await _chores(db_session, kid, 10)
        assert _b(await BadgeService.sync(db_session, kid), "chores").tier == 1
        await db_session.execute(                                 # a parent re-grades one as missed
            update(TaskAssignment).where(TaskAssignment.id == rows[0].id).values(completion_grade="missed")
        )
        await db_session.commit()
        resp = await BadgeService.sync(db_session, kid)
        chores = _b(resp, "chores")
        assert chores.count == 9 and chores.tier == 1 and chores.next_target == 50
        assert chores.earned_at is not None and resp.earned_total == 1

    async def test_a_moved_kid_earns_the_tier_again_in_the_new_family(self, db_session, test_child_user):
        # invitation_service can move an existing kid account into another
        # family; the old family's rows must not block the new family's tier.
        kid = test_child_user
        old_family_id = kid.family_id
        await _cup(db_session, kid, 1)
        assert _b(await BadgeService.sync(db_session, kid), "cup").tier == 1
        other = Family(name="Other")
        db_session.add(other)
        await db_session.commit()
        kid.family_id = other.id
        await db_session.commit()
        await _cup(db_session, kid, 1)                            # wins a season in the new family
        resp = await BadgeService.sync(db_session, kid)
        assert _b(resp, "cup").count == 1 and _b(resp, "cup").tier == 1
        assert [(u.badge, u.tier) for u in resp.unseen] == [("cup", 1)]
        held_in = (await db_session.execute(
            select(UserBadge.family_id).where(UserBadge.user_id == kid.id)
        )).scalars().all()
        assert sorted(held_in, key=str) == sorted([old_family_id, other.id], key=str)

    async def test_ack_only_marks_the_callers_own_rows(self, db_session, test_child_user, test_teen_user):
        await _cup(db_session, test_child_user, 1)
        await _cup(db_session, test_teen_user, 2)
        mine = (await BadgeService.sync(db_session, test_child_user)).unseen
        theirs = (await BadgeService.sync(db_session, test_teen_user)).unseen
        await BadgeService.ack(db_session, test_child_user, [mine[0].id, theirs[0].id])
        assert (await BadgeService.sync(db_session, test_child_user)).unseen == []
        assert len((await BadgeService.sync(db_session, test_teen_user)).unseen) == 1


class TestModuleGating:
    async def _gig_badge(self, db, kid):
        gig = GigOffering(family_id=kid.family_id, title="Wash the car", points=50)
        db.add(gig)
        await db.commit()
        db.add(GigClaim(gig_id=gig.id, family_id=kid.family_id, claimed_by=kid.id, status=GigClaimStatus.APPROVED))
        await db.commit()

    async def test_gigs_module_off_hides_gigs_and_saver_but_keeps_rows(self, db_session, test_family, test_child_user):
        kid = test_child_user
        await self._gig_badge(db_session, kid)
        assert _b(await BadgeService.sync(db_session, kid), "gigs").tier == 1
        test_family.enabled_modules = ["chat"]
        await db_session.commit()
        off = await BadgeService.sync(db_session, kid)
        assert [b.badge for b in off.badges] == ["chores", "streak", "perfect_week", "extra_mile", "rewards", "cup"]
        assert off.earned_total == 0 and off.unseen == []
        assert await _stored(db_session, kid) == 1               # the row is kept
        test_family.enabled_modules = None
        await db_session.commit()
        on = await BadgeService.sync(db_session, kid)
        assert _b(on, "gigs").tier == 1 and on.earned_total == 1

    async def test_gigs_module_off_does_not_award_new_gig_badges(self, db_session, test_family, test_child_user):
        kid = test_child_user
        test_family.enabled_modules = ["chat"]
        await db_session.commit()
        await self._gig_badge(db_session, kid)
        await BadgeService.sync(db_session, kid)
        assert await _stored(db_session, kid) == 0

    async def test_earned_counts_group_per_kid_and_respect_visibility(self, db_session, test_family,
                                                                      test_child_user, test_teen_user):
        await self._gig_badge(db_session, test_child_user)
        await _cup(db_session, test_child_user, 1)
        await BadgeService.sync(db_session, test_child_user)
        await BadgeService.sync(db_session, test_teen_user)
        all_on = await BadgeService.visible_for(db_session, test_family.id)
        counts = await BadgeService.earned_counts(db_session, test_family.id, all_on)
        assert counts.get(test_child_user.id) == 2 and counts.get(test_teen_user.id) is None
        assert isinstance(counts[test_child_user.id], int)
        test_family.enabled_modules = ["chat"]
        await db_session.commit()
        gated = await BadgeService.earned_counts(
            db_session, test_family.id, await BadgeService.visible_for(db_session, test_family.id))
        assert gated.get(test_child_user.id) == 1                # the gig badge is hidden
