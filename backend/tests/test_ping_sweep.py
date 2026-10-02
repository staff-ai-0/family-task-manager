"""UX-D4a evening sweep against the test DB.

Injected clocks are derived from the real today (never a hard-coded date) and
land on a Wednesday, so no test sits on a week edge. The double-run test uses
the real clock, in a timezone where it is 18:xx right now.
"""
from datetime import datetime, time, timedelta, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select

from app.models.family import Family
from app.models.gig import GigOffering
from app.models.notification import Notification, NotificationType as NT
from app.models.point_transaction import PointTransaction
from app.models.push_subscription import PushSubscription
from app.models.task_assignment import ApprovalStatus, AssignmentStatus, TaskAssignment
from app.models.task_template import AssignmentType, TaskTemplate
from app.models.user import User, UserRole
from app.models.weekly_quest import WeeklyQuest
from app.services.ping_service import PING_TAG, PingService
from app.services.quest_service import week_monday

UTC = ZoneInfo("UTC")


def _wednesday(tz=UTC):
    today = datetime.now(tz).date()
    return today + timedelta(days=(2 - today.weekday()) % 7)


def _at(day, hour, tz=UTC):
    return datetime.combine(day, time(hour, 0), tzinfo=tz)


async def _template(db, family_id, *, bonus=False):
    t = TaskTemplate(id=uuid4(), title="Chore", points=10, interval_days=1,
                     assignment_type=AssignmentType.AUTO, is_bonus=bonus, is_active=True, family_id=family_id)
    db.add(t)
    await db.commit()
    return t


async def _assign(db, kid, template, day, status=AssignmentStatus.PENDING, *, grade=None,
                  approval=ApprovalStatus.NONE):
    a = TaskAssignment(family_id=template.family_id, template_id=template.id, assigned_to=kid.id,
                       status=status, approval_status=approval, completion_grade=grade,
                       assigned_date=day, week_of=day - timedelta(days=day.weekday()))
    db.add(a)
    await db.commit()
    return a


async def _subscribe(db, user):
    db.add(PushSubscription(user_id=user.id, endpoint=f"https://push.example/{uuid4()}", p256dh="p", auth="a"))
    await db.commit()


async def _streak(db, kid, chore, today, days=3):
    """`days` finished days right before today → a streak of `days`."""
    for i in range(1, days + 1):
        await _assign(db, kid, chore, today - timedelta(days=i), AssignmentStatus.COMPLETED)


async def _quest(db, kid, today, quest="on_time", target=2, bonus=20):
    q = WeeklyQuest(family_id=kid.family_id, user_id=kid.id, week_start=week_monday(today), quest=quest,
                    target=target, bonus_points=bonus, created_at=datetime.now(timezone.utc))
    db.add(q)
    await db.commit()
    return q


async def _pings(db, user=None):
    q = select(Notification).where(Notification.type.in_([NT.STREAK_AT_RISK, NT.QUEST_NUDGE]))
    if user is not None:
        q = q.where(Notification.user_id == user.id)
    return list((await db.execute(q.order_by(Notification.created_at))).scalars().all())


async def _at_risk_kid(db, kid, today, *, days=3, open_chores=1):
    chore = await _template(db, kid.family_id)
    await _streak(db, kid, chore, today, days)
    for _ in range(open_chores):
        await _assign(db, kid, chore, today)
    await _subscribe(db, kid)
    return chore


class TestStreakPing:
    async def test_sends_the_free_pass_wording_when_the_pass_is_unused(self, db_session, test_family, test_child_user):
        today = _wednesday()
        await _at_risk_kid(db_session, test_child_user, today, days=4, open_chores=2)
        assert await PingService.run_evening_sweep(db_session, now=_at(today, 18)) == 1
        (n,) = await _pings(db_session)
        assert n.type == NT.STREAK_AT_RISK and n.user_id == test_child_user.id and n.family_id == test_family.id
        assert n.title == "🔥 Keep your 4-day streak"
        assert n.body == "2 chores left today. Finish them and save your free pass 🛡️."
        assert n.link == "/dashboard"
        assert n.expires_at == _at(today + timedelta(days=1), 0)

    async def test_ends_tonight_wording_when_the_pass_is_spent_and_in_spanish(self, db_session, test_family, test_child_user):
        kid = test_child_user
        kid.preferred_lang = "es"
        await db_session.commit()
        today = _wednesday()
        chore = await _template(db_session, kid.family_id)
        monday = week_monday(today)
        await _assign(db_session, kid, chore, monday, AssignmentStatus.OVERDUE)          # this week's miss → pass spent
        await _assign(db_session, kid, chore, today - timedelta(days=1), AssignmentStatus.COMPLETED)
        for i in (1, 2, 3):
            await _assign(db_session, kid, chore, monday - timedelta(days=i), AssignmentStatus.COMPLETED)
        await _assign(db_session, kid, chore, today)
        await _subscribe(db_session, kid)
        assert await PingService.run_evening_sweep(db_session, now=_at(today, 18)) == 1
        (n,) = await _pings(db_session)
        assert n.title == "🔥 Tu racha de 4 días termina esta noche"
        assert n.body == "Te falta 1 tarea hoy. Termínala para conservarla."

    async def test_a_short_streak_sends_nothing(self, db_session, test_family, test_child_user):
        today = _wednesday()
        await _at_risk_kid(db_session, test_child_user, today, days=2)
        assert await PingService.run_evening_sweep(db_session, now=_at(today, 18)) == 0
        assert await _pings(db_session) == []

    async def test_nothing_left_to_do_sends_nothing(self, db_session, test_family, test_child_user):
        today = _wednesday()
        chore = await _template(db_session, test_child_user.family_id)
        await _streak(db_session, test_child_user, chore, today, 5)
        await _assign(db_session, test_child_user, chore, today, AssignmentStatus.COMPLETED)
        await _subscribe(db_session, test_child_user)
        assert await PingService.run_evening_sweep(db_session, now=_at(today, 18)) == 0

    async def test_a_day_already_lost_sends_nothing(self, db_session, test_family, test_child_user):
        today = _wednesday()
        chore = await _at_risk_kid(db_session, test_child_user, today, days=5)
        await _assign(db_session, test_child_user, chore, today, AssignmentStatus.COMPLETED, grade="missed")
        assert await PingService.run_evening_sweep(db_session, now=_at(today, 18)) == 0

    async def test_a_rejected_chore_reopened_today_sends_nothing(self, db_session, test_family, test_child_user):
        today = _wednesday()
        chore = await _at_risk_kid(db_session, test_child_user, today, days=5)
        await _assign(db_session, test_child_user, chore, today, AssignmentStatus.PENDING, grade="missed",
                      approval=ApprovalStatus.REJECTED)
        assert await PingService.run_evening_sweep(db_session, now=_at(today, 18)) == 0


class TestWhoAndWhen:
    @pytest.mark.parametrize("hour,expected", [(17, 0), (18, 1), (19, 1), (20, 1), (21, 0)])
    async def test_only_inside_the_window(self, db_session, test_family, test_child_user, hour, expected):
        today = _wednesday()
        await _at_risk_kid(db_session, test_child_user, today)
        assert await PingService.run_evening_sweep(db_session, now=_at(today, hour)) == expected

    async def test_each_family_is_judged_by_its_own_clock(self, db_session, test_family, test_child_user):
        tokyo = ZoneInfo("Asia/Tokyo")
        far = Family(name="Tokyo", timezone="Asia/Tokyo")
        db_session.add(far)
        await db_session.commit()
        far_kid = User(email="tokyo@test.com", password_hash="x", name="Far Kid", role=UserRole.CHILD,
                       family_id=far.id, email_verified=True, points=0)
        db_session.add(far_kid)
        await db_session.commit()
        today = _wednesday()
        now = _at(today, 18)                                   # 18:00 UTC = 03:00 next day in Tokyo
        await _at_risk_kid(db_session, test_child_user, today)
        await _at_risk_kid(db_session, far_kid, now.astimezone(tokyo).date())
        assert await PingService.run_evening_sweep(db_session, now=now) == 1
        assert [n.user_id for n in await _pings(db_session)] == [test_child_user.id]
        # 09:00 UTC is 18:00 in Tokyo: now it is their turn, and only theirs.
        tokyo_evening = _at(now.astimezone(tokyo).date(), 18, tokyo)
        assert await PingService.run_evening_sweep(db_session, now=tokyo_evening) == 1
        assert {n.user_id for n in await _pings(db_session)} == {test_child_user.id, far_kid.id}
        assert [n.family_id for n in await _pings(db_session, far_kid)] == [far.id]

    async def test_switch_off_skips_the_family(self, db_session, test_family, test_child_user):
        today = _wednesday()
        await _at_risk_kid(db_session, test_child_user, today)
        test_family.smart_reminders_enabled = False
        await db_session.commit()
        assert await PingService.run_evening_sweep(db_session, now=_at(today, 18)) == 0
        assert await _pings(db_session) == []

    async def test_no_subscription_means_no_row_at_all(self, db_session, test_family, test_child_user):
        today = _wednesday()
        chore = await _template(db_session, test_child_user.family_id)
        await _streak(db_session, test_child_user, chore, today, 5)
        await _assign(db_session, test_child_user, chore, today)
        assert await PingService.run_evening_sweep(db_session, now=_at(today, 18)) == 0
        assert (await db_session.execute(select(func.count()).select_from(Notification))).scalar() == 0

    async def test_parents_and_unapproved_members_are_never_pinged(self, db_session, test_family, test_parent_user, test_teen_user):
        today = _wednesday()
        await _at_risk_kid(db_session, test_parent_user, today)
        await _at_risk_kid(db_session, test_teen_user, today)
        test_teen_user.approval_status = "pending"
        await db_session.commit()
        assert await PingService.run_evening_sweep(db_session, now=_at(today, 18)) == 0

    async def test_one_family_failing_does_not_stop_the_next(self, db_session, test_family, test_child_user):
        broken = Family(name="Broken", timezone="Etc/GMT+1")
        db_session.add(broken)
        await db_session.commit()
        today = _wednesday()
        await _at_risk_kid(db_session, test_child_user, today)
        from app.services import ping_service
        real = ping_service._safe_zoneinfo

        def flaky(name):
            if name == "Etc/GMT+1":
                raise RuntimeError("boom")
            return real(name)

        with patch.object(ping_service, "_safe_zoneinfo", side_effect=flaky):
            assert await PingService.run_evening_sweep(db_session, now=_at(today, 18)) == 1

    async def test_a_teen_is_pinged_like_a_child(self, db_session, test_family, test_teen_user):
        today = _wednesday()
        await _at_risk_kid(db_session, test_teen_user, today)
        assert await PingService.run_evening_sweep(db_session, now=_at(today, 18)) == 1

    async def test_one_kid_failing_does_not_stop_the_next(self, db_session, test_family, test_child_user, test_teen_user):
        today = _wednesday()
        await _at_risk_kid(db_session, test_child_user, today)
        await _at_risk_kid(db_session, test_teen_user, today)
        real = PingService._ping_kid
        # Ids captured up front: the sweep rolls back after the failure, which
        # expires these fixtures, and touching one afterwards is a lazy load.
        broken, teen_id = test_child_user.id, test_teen_user.id

        async def flaky(db, fam, kid_id, *args, **kwargs):
            if kid_id == broken:
                raise RuntimeError("boom")
            return await real(db, fam, kid_id, *args, **kwargs)

        with patch.object(PingService, "_ping_kid", side_effect=flaky):
            assert await PingService.run_evening_sweep(db_session, now=_at(today, 18)) == 1
        assert [n.user_id for n in await _pings(db_session)] == [teen_id]


class TestOncePerDay:
    async def test_a_second_run_in_the_same_evening_sends_nothing(self, db_session, test_family, test_child_user):
        """Real clock, no injection: the family lives in whichever fixed-offset
        zone reads 18:xx right now, so both runs are inside the window."""
        real_now = datetime.now(timezone.utc)
        name = next(
            f"Etc/GMT{off:+d}" for off in range(-14, 13)
            if real_now.astimezone(ZoneInfo(f"Etc/GMT{off:+d}")).hour == 18
        )
        test_family.timezone = name
        await db_session.commit()
        today = real_now.astimezone(ZoneInfo(name)).date()
        await _at_risk_kid(db_session, test_child_user, today)
        assert await PingService.run_evening_sweep(db_session) == 1
        assert await PingService.run_evening_sweep(db_session) == 0
        assert len(await _pings(db_session)) == 1

    async def test_yesterdays_reminder_does_not_block_today(self, db_session, test_family, test_child_user):
        today = _wednesday()
        await _at_risk_kid(db_session, test_child_user, today)
        db_session.add(Notification(family_id=test_family.id, user_id=test_child_user.id, type=NT.STREAK_AT_RISK,
                                    title="old", created_at=_at(today - timedelta(days=1), 18)))
        await db_session.commit()
        assert await PingService.run_evening_sweep(db_session, now=_at(today, 18)) == 1

    async def test_a_reminder_earlier_today_blocks_either_kind(self, db_session, test_family, test_child_user):
        today = _wednesday()
        await _at_risk_kid(db_session, test_child_user, today)
        db_session.add(Notification(family_id=test_family.id, user_id=test_child_user.id, type=NT.QUEST_NUDGE,
                                    title="earlier", created_at=_at(today, 18)))
        await db_session.commit()
        assert await PingService.run_evening_sweep(db_session, now=_at(today, 19)) == 0

    async def test_a_siblings_reminder_does_not_block_this_kid(self, db_session, test_family, test_child_user, test_teen_user):
        today = _wednesday()
        await _at_risk_kid(db_session, test_child_user, today)
        db_session.add(Notification(family_id=test_family.id, user_id=test_teen_user.id, type=NT.STREAK_AT_RISK,
                                    title="the teen's", created_at=_at(today, 18)))
        await db_session.commit()
        child_id = test_child_user.id
        assert await PingService.run_evening_sweep(db_session, now=_at(today, 19)) == 1
        assert child_id in [n.user_id for n in await _pings(db_session)]


class TestQuestNudge:
    async def _one_away(self, db, kid, today, quest="on_time", target=2):
        chore = await _template(db, kid.family_id)
        await _assign(db, kid, chore, today, AssignmentStatus.COMPLETED)     # counts 1 toward the goal
        await _assign(db, kid, chore, today)                                 # the missing step
        await _quest(db, kid, today, quest, target=target)
        await _subscribe(db, kid)
        return chore

    async def test_sends_when_one_step_away(self, db_session, test_family, test_child_user):
        today = _wednesday()
        await self._one_away(db_session, test_child_user, today)
        assert await PingService.run_evening_sweep(db_session, now=_at(today, 18)) == 1
        (n,) = await _pings(db_session)
        assert n.type == NT.QUEST_NUDGE
        assert (n.title, n.body) == ("🏁 1 away from this week's quest", "Finish it for +20 points.")
        assert n.expires_at == _at(week_monday(today) + timedelta(days=7), 0)

    async def test_two_steps_away_sends_nothing(self, db_session, test_family, test_child_user):
        today = _wednesday()
        chore = await _template(db_session, test_child_user.family_id)
        await _assign(db_session, test_child_user, chore, today)
        await _quest(db_session, test_child_user, today, "on_time", target=2)
        await _subscribe(db_session, test_child_user)
        assert await PingService.run_evening_sweep(db_session, now=_at(today, 18)) == 0

    async def test_once_per_week(self, db_session, test_family, test_child_user):
        today = _wednesday()
        await self._one_away(db_session, test_child_user, today)
        db_session.add(Notification(family_id=test_family.id, user_id=test_child_user.id, type=NT.QUEST_NUDGE,
                                    title="monday", created_at=_at(week_monday(today), 18)))
        await db_session.commit()
        assert await PingService.run_evening_sweep(db_session, now=_at(today, 18)) == 0

    async def test_last_weeks_nudge_does_not_block_this_week(self, db_session, test_family, test_child_user):
        today = _wednesday()
        await self._one_away(db_session, test_child_user, today)
        db_session.add(Notification(family_id=test_family.id, user_id=test_child_user.id, type=NT.QUEST_NUDGE,
                                    title="last week", created_at=_at(week_monday(today) - timedelta(days=2), 18)))
        await db_session.commit()
        assert await PingService.run_evening_sweep(db_session, now=_at(today, 18)) == 1

    async def test_quests_off_sends_nothing(self, db_session, test_family, test_child_user):
        today = _wednesday()
        await self._one_away(db_session, test_child_user, today)
        for value in (0, None):
            test_family.quest_bonus_points = value
            await db_session.commit()
            assert await PingService.run_evening_sweep(db_session, now=_at(today, 18)) == 0

    async def test_a_paid_quest_sends_nothing(self, db_session, test_family, test_child_user):
        today = _wednesday()
        await self._one_away(db_session, test_child_user, today)
        quest = (await db_session.execute(select(WeeklyQuest))).scalar_one()
        quest.rewarded_at = datetime.now(timezone.utc)
        await db_session.commit()
        assert await PingService.run_evening_sweep(db_session, now=_at(today, 18)) == 0

    async def test_missing_step_not_doable_today_sends_nothing(self, db_session, test_family, test_child_user):
        today = _wednesday()
        chore = await _template(db_session, test_child_user.family_id)
        await _assign(db_session, test_child_user, chore, today, AssignmentStatus.COMPLETED)
        await _assign(db_session, test_child_user, chore, today + timedelta(days=1))     # only tomorrow's left
        await _quest(db_session, test_child_user, today, "on_time", target=2)
        await _subscribe(db_session, test_child_user)
        assert await PingService.run_evening_sweep(db_session, now=_at(today, 18)) == 0

    async def test_go_getter_needs_an_open_gig(self, db_session, test_family, test_child_user):
        today = _wednesday()
        await _quest(db_session, test_child_user, today, "go_getter", target=1)
        await _subscribe(db_session, test_child_user)
        assert await PingService.run_evening_sweep(db_session, now=_at(today, 18)) == 0
        db_session.add(GigOffering(family_id=test_family.id, title="Wash car", points=50))
        await db_session.commit()
        assert await PingService.run_evening_sweep(db_session, now=_at(today, 18)) == 1

    async def test_the_sweep_never_creates_a_quest_or_pays(self, db_session, test_family, test_child_user):
        today = _wednesday()
        chore = await _template(db_session, test_child_user.family_id)
        await _assign(db_session, test_child_user, chore, today)
        await _subscribe(db_session, test_child_user)
        assert await PingService.run_evening_sweep(db_session, now=_at(today, 18)) == 0
        assert (await db_session.execute(select(func.count()).select_from(WeeklyQuest))).scalar() == 0
        assert (await db_session.execute(select(func.count()).select_from(PointTransaction))).scalar() == 0

    async def test_streak_wins_and_the_quest_stays_eligible(self, db_session, test_family, test_child_user):
        kid = test_child_user
        today = _wednesday()
        # The streak's Monday and Tuesday chores also count toward the quest,
        # so the goal is 4: 3 done (Mon, Tue, one today) and one still open.
        chore = await self._one_away(db_session, kid, today, target=4)
        await _streak(db_session, kid, chore, today, 3)
        assert await PingService.run_evening_sweep(db_session, now=_at(today, 18)) == 1
        (n,) = await _pings(db_session)
        assert n.type == NT.STREAK_AT_RISK
        # A streak reminder on an earlier day never uses up the quest's one nudge.
        n.created_at = _at(today - timedelta(days=1), 18)
        await db_session.commit()
        with patch("app.services.ping_service.streak_ping", return_value=None):
            assert await PingService.run_evening_sweep(db_session, now=_at(today, 18)) == 1
        # Sorted, not ordered by time: the streak row was re-dated by the test.
        assert sorted(p.type for p in await _pings(db_session)) == [NT.QUEST_NUDGE, NT.STREAK_AT_RISK]


class TestPushPayload:
    async def test_push_is_tagged_and_links_home(self, db_session, test_family, test_child_user):
        today = _wednesday()
        await _at_risk_kid(db_session, test_child_user, today)
        with patch("app.services.push_service.PushService.send_to_user", new_callable=AsyncMock) as send:
            assert await PingService.run_evening_sweep(db_session, now=_at(today, 18)) == 1
        assert send.await_count == 1
        _db, user_id, payload = send.await_args.args
        assert user_id == test_child_user.id
        assert payload["tag"] == PING_TAG and payload["url"] == "/dashboard"
        assert payload["title"] == "🔥 Keep your 3-day streak"

    async def test_one_familys_switch_does_not_affect_another(self, db_session, test_family, test_child_user):
        other = Family(name="Other")
        db_session.add(other)
        await db_session.commit()
        other_kid = User(email="ok@test.com", password_hash="x", name="OK", role=UserRole.CHILD,
                         family_id=other.id, email_verified=True, points=0)
        db_session.add(other_kid)
        await db_session.commit()
        today = _wednesday()
        await _at_risk_kid(db_session, test_child_user, today)
        await _at_risk_kid(db_session, other_kid, today)
        other.smart_reminders_enabled = False                  # their switch, not ours
        await db_session.commit()
        ours, theirs = test_child_user.id, other_kid.id
        assert await PingService.run_evening_sweep(db_session, now=_at(today, 18)) == 1
        assert [n.user_id for n in await _pings(db_session)] == [ours]
        assert theirs not in [n.user_id for n in await _pings(db_session)]
