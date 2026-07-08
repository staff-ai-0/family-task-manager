"""Auto late penalty: mark_overdue_all instantiates Consequence rows.

Verifies:
- Templates with auto_late_penalty=False do NOT create consequences.
- Templates with auto_late_penalty=True and valid restriction/severity DO.
- Invalid restriction strings are silently skipped (no crash).
- Sweep is idempotent: a second run does NOT duplicate consequences
  because the assignment already moved past PENDING.
"""

import pytest
from datetime import date, datetime, timedelta, timezone
from sqlalchemy import select

from app.models.task_template import TaskTemplate
from app.models.task_assignment import TaskAssignment, AssignmentStatus
from app.models.consequence import (
    Consequence,
    ConsequenceSeverity,
    RestrictionType,
)
from app.services.task_assignment_service import TaskAssignmentService


async def _make_overdue_assignment(
    db_session,
    family,
    user,
    *,
    auto_late_penalty: bool = False,
    restriction: str | None = None,
    severity: str | None = None,
    duration: int = 1,
) -> TaskAssignment:
    tmpl = TaskTemplate(
        title="Make Bed",
        points=0,
        effort_level=1,
        interval_days=1,
        is_bonus=False,
        auto_late_penalty=auto_late_penalty,
        late_restriction_type=restriction,
        late_severity=severity,
        late_duration_days=duration,
        family_id=family.id,
        created_by=user.id,
    )
    db_session.add(tmpl)
    await db_session.flush()
    yesterday = date.today() - timedelta(days=1)
    assignment = TaskAssignment(
        template_id=tmpl.id,
        assigned_to=user.id,
        family_id=family.id,
        status=AssignmentStatus.PENDING,
        assigned_date=yesterday,
        week_of=yesterday - timedelta(days=yesterday.weekday()),
    )
    db_session.add(assignment)
    await db_session.commit()
    await db_session.refresh(assignment)
    return assignment


class TestAutoLatePenalty:
    async def test_no_penalty_when_flag_off(
        self, db_session, test_family, test_child_user
    ):
        await _make_overdue_assignment(
            db_session, test_family, test_child_user, auto_late_penalty=False
        )
        flipped = await TaskAssignmentService.mark_overdue_all(db_session)
        assert flipped == 1
        rows = (await db_session.execute(select(Consequence))).scalars().all()
        assert rows == []

    async def test_penalty_created_when_flag_on(
        self, db_session, test_family, test_child_user
    ):
        a = await _make_overdue_assignment(
            db_session,
            test_family,
            test_child_user,
            auto_late_penalty=True,
            restriction="screen_time",
            severity="medium",
            duration=2,
        )
        flipped = await TaskAssignmentService.mark_overdue_all(db_session)
        assert flipped == 1
        rows = (
            await db_session.execute(
                select(Consequence).where(Consequence.triggered_by_assignment_id == a.id)
            )
        ).scalars().all()
        assert len(rows) == 1
        c = rows[0]
        assert c.restriction_type == RestrictionType.SCREEN_TIME
        assert c.severity == ConsequenceSeverity.MEDIUM
        assert c.duration_days == 2
        assert c.applied_to_user == test_child_user.id
        assert c.family_id == test_family.id
        assert c.active is True

    async def test_penalty_skipped_when_restriction_missing(
        self, db_session, test_family, test_child_user
    ):
        await _make_overdue_assignment(
            db_session,
            test_family,
            test_child_user,
            auto_late_penalty=True,
            restriction=None,
            severity="low",
        )
        flipped = await TaskAssignmentService.mark_overdue_all(db_session)
        assert flipped == 1
        rows = (await db_session.execute(select(Consequence))).scalars().all()
        assert rows == []

    async def test_penalty_skipped_on_invalid_restriction(
        self, db_session, test_family, test_child_user
    ):
        await _make_overdue_assignment(
            db_session,
            test_family,
            test_child_user,
            auto_late_penalty=True,
            restriction="bogus_value",
            severity="low",
        )
        flipped = await TaskAssignmentService.mark_overdue_all(db_session)
        assert flipped == 1
        rows = (await db_session.execute(select(Consequence))).scalars().all()
        assert rows == []

    async def test_sweep_is_idempotent(
        self, db_session, test_family, test_child_user
    ):
        a = await _make_overdue_assignment(
            db_session,
            test_family,
            test_child_user,
            auto_late_penalty=True,
            restriction="rewards",
            severity="low",
            duration=1,
        )
        await TaskAssignmentService.mark_overdue_all(db_session)
        await TaskAssignmentService.mark_overdue_all(db_session)
        rows = (
            await db_session.execute(
                select(Consequence).where(Consequence.triggered_by_assignment_id == a.id)
            )
        ).scalars().all()
        assert len(rows) == 1

    async def test_pending_member_flips_without_penalty_or_notification(
        self, db_session, test_family
    ):
        """Legacy rows held by a join-code signup still awaiting parental
        approval flip to OVERDUE (bookkeeping stays universal) but never
        spawn a Consequence or a late-penalty notification — the account
        cannot log in, so punishing it is pure noise."""
        from app.models.notification import Notification
        from app.models.user import APPROVAL_PENDING, User, UserRole

        pending = User(
            email="pending-penalty@test.com",
            name="Pending Kid",
            role=UserRole.CHILD,
            family_id=test_family.id,
            approval_status=APPROVAL_PENDING,
            points=0,
        )
        db_session.add(pending)
        await db_session.commit()
        await db_session.refresh(pending)

        a = await _make_overdue_assignment(
            db_session,
            test_family,
            pending,
            auto_late_penalty=True,
            restriction="screen_time",
            severity="medium",
        )
        flipped = await TaskAssignmentService.mark_overdue_all(db_session)
        assert flipped == 1
        await db_session.refresh(a)
        assert a.status == AssignmentStatus.OVERDUE

        rows = (await db_session.execute(select(Consequence))).scalars().all()
        assert rows == []
        notifs = (
            await db_session.execute(
                select(Notification).where(Notification.user_id == pending.id)
            )
        ).scalars().all()
        assert notifs == []

    async def test_inactive_member_flips_without_penalty(
        self, db_session, test_family, test_child_user
    ):
        """Deactivated members are outside the pipeline too: the flip still
        happens but no automatic Consequence is created."""
        a = await _make_overdue_assignment(
            db_session,
            test_family,
            test_child_user,
            auto_late_penalty=True,
            restriction="rewards",
            severity="low",
        )
        test_child_user.is_active = False
        await db_session.commit()

        flipped = await TaskAssignmentService.mark_overdue_all(db_session)
        assert flipped == 1
        await db_session.refresh(a)
        assert a.status == AssignmentStatus.OVERDUE

        rows = (await db_session.execute(select(Consequence))).scalars().all()
        assert rows == []
