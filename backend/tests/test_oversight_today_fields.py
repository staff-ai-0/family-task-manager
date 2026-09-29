"""KidSummary "today" counts for the parent hub (UX-C2).

The hub's per-kid row must say exactly what the kid's own home says:
required_total_today / required_done_today mirror get_daily_progress, and
overdue_count mirrors list_open_mandatory_before. Asserted as parity, so a
future change to either definition fails here instead of drifting.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.models.notification import Notification, NotificationType as NT
from app.models.task_assignment import ApprovalStatus, AssignmentStatus, TaskAssignment
from app.models.task_template import AssignmentType, TaskTemplate
from app.services.oversight_service import OversightService
from app.services.task_assignment_service import TaskAssignmentService

from conftest import family_local_today


async def _template(db, family, *, bonus=False, title="Chore"):
    t = TaskTemplate(
        id=uuid4(), title=title, points=10, interval_days=1,
        assignment_type=AssignmentType.AUTO, is_bonus=bonus, is_active=True,
        family_id=family.id,
    )
    db.add(t)
    await db.commit()
    return t


async def _assign(db, family_id, template, kid, day, status, approval=ApprovalStatus.NONE):
    a = TaskAssignment(
        family_id=family_id, template_id=template.id, assigned_to=kid.id,
        status=status, approval_status=approval,
        assigned_date=day, week_of=day - timedelta(days=day.weekday()),
    )
    db.add(a)
    await db.commit()
    return a


async def _seed_mixed_day(db, family, kid):
    today = await family_local_today(db, family.id)
    chore = await _template(db, family, title="Dishes")
    bonus = await _template(db, family, bonus=True, title="Extra")
    fid = family.id
    await _assign(db, fid, chore, kid, today, AssignmentStatus.PENDING)
    await _assign(db, fid, chore, kid, today, AssignmentStatus.COMPLETED)
    await _assign(db, fid, chore, kid, today, AssignmentStatus.COMPLETED, ApprovalStatus.PENDING)
    await _assign(db, fid, chore, kid, today, AssignmentStatus.CANCELLED)
    await _assign(db, fid, bonus, kid, today, AssignmentStatus.PENDING)
    await _assign(db, fid, chore, kid, today - timedelta(days=1), AssignmentStatus.OVERDUE)
    await _assign(db, fid, chore, kid, today - timedelta(days=3), AssignmentStatus.PENDING)
    await _assign(db, fid, chore, kid, today - timedelta(days=2), AssignmentStatus.COMPLETED)
    await _assign(db, fid, bonus, kid, today - timedelta(days=1), AssignmentStatus.PENDING)
    return today


def _card(summary, kid):
    return next(m for m in summary.members if m.user_id == kid.id)


class TestTodayCounts:
    async def test_counts_match_the_kids_own_progress(
        self, db_session, test_family, test_child_user, test_teen_user,
    ):
        today = await _seed_mixed_day(db_session, test_family, test_child_user)
        summary = await OversightService.get_summary(db_session, test_family.id)
        card = _card(summary, test_child_user)
        progress = await TaskAssignmentService.get_daily_progress(
            db_session, test_child_user.id, test_family.id,
        )
        overdue = await TaskAssignmentService.list_open_mandatory_before(
            db_session, test_child_user.id, test_family.id, today,
        )
        # pending + completed + completed-awaiting-approval + cancelled (bonus excluded)
        assert card.required_total_today == progress["required_total"] == 4
        assert card.required_done_today == progress["required_completed"] == 2
        assert card.required_open_today == 1
        assert card.overdue_count == len(overdue) == 2
        teen = _card(summary, test_teen_user)
        assert (
            teen.required_total_today, teen.required_done_today,
            teen.required_open_today, teen.overdue_count,
        ) == (0, 0, 0, 0)

    async def test_today_is_the_familys_day(
        self, db_session, test_family, test_child_user,
    ):
        test_family.timezone = "Pacific/Kiritimati"  # UTC+14
        await db_session.commit()
        today = await family_local_today(db_session, test_family.id)
        chore = await _template(db_session, test_family)
        await _assign(db_session, test_family.id, chore, test_child_user, today, AssignmentStatus.PENDING)
        card = _card(await OversightService.get_summary(db_session, test_family.id), test_child_user)
        assert (card.required_total_today, card.required_open_today, card.overdue_count) == (1, 1, 0)

    async def test_other_family_rows_never_counted(
        self, db_session, test_family, test_child_user, other_family,
    ):
        today = await family_local_today(db_session, test_family.id)
        foreign = await _template(db_session, other_family)
        # Rows stamped with ANOTHER family id — the family filter must drop them.
        await _assign(db_session, other_family.id, foreign, test_child_user, today, AssignmentStatus.PENDING)
        await _assign(db_session, other_family.id, foreign, test_child_user, today - timedelta(days=1), AssignmentStatus.OVERDUE)
        db_session.add(Notification(
            family_id=other_family.id, user_id=test_child_user.id,
            type=NT.PARENT_NUDGE, title="⏰",
        ))
        await db_session.commit()
        card = _card(await OversightService.get_summary(db_session, test_family.id), test_child_user)
        assert (card.required_total_today, card.required_open_today, card.overdue_count) == (0, 0, 0)
        assert card.last_nudged_at is None

    async def test_last_nudged_at_is_the_latest_nudge(
        self, db_session, test_family, test_child_user,
    ):
        card = _card(await OversightService.get_summary(db_session, test_family.id), test_child_user)
        assert card.last_nudged_at is None
        now = datetime.now(timezone.utc)
        for ts in (now - timedelta(hours=5), now - timedelta(hours=1)):
            db_session.add(Notification(
                family_id=test_family.id, user_id=test_child_user.id,
                type=NT.PARENT_NUDGE, title="⏰", created_at=ts,
            ))
        # A newer notification of another type must not count.
        db_session.add(Notification(
            family_id=test_family.id, user_id=test_child_user.id,
            type=NT.TASK_DUE, title="x", created_at=now,
        ))
        await db_session.commit()
        card = _card(await OversightService.get_summary(db_session, test_family.id), test_child_user)
        assert card.last_nudged_at is not None
        assert abs((card.last_nudged_at - (now - timedelta(hours=1))).total_seconds()) < 1
