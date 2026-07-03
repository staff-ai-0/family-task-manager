"""Overdue mandatory tasks must stay visible and unlockable.

Regression: the sweep flips a prior-day PENDING mandatory to OVERDUE, which
then vanished from today's dashboard list while still blocking bonus/gigs
forever — the kid saw "N/N done" next to a generic "complete all required"
message with no way to find the blocker. get_daily_progress now returns the
open prior-day mandatory assignments so the dashboard can render "Atrasadas".
"""
from datetime import date, timedelta
from uuid import uuid4

import pytest

from app.models.task_assignment import TaskAssignment, AssignmentStatus
from app.services.task_assignment_service import TaskAssignmentService


def _week_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


async def _assign(db, family, user, template, when, status=AssignmentStatus.PENDING):
    a = TaskAssignment(
        id=uuid4(), template_id=template.id, assigned_to=user.id,
        family_id=family.id, assigned_date=when, week_of=_week_of(when),
        status=status,
    )
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return a


@pytest.mark.asyncio
async def test_overdue_prior_day_mandatory_is_surfaced_and_blocks_bonus(
    db_session, test_family, test_child_user, mandatory_template_factory
):
    mand = await mandatory_template_factory(family=test_family)
    yesterday = date.today() - timedelta(days=1)
    await _assign(
        db_session, test_family, test_child_user, mand, yesterday,
        status=AssignmentStatus.OVERDUE,
    )

    progress = await TaskAssignmentService.get_daily_progress(
        db_session, user_id=test_child_user.id, family_id=test_family.id,
    )

    # Blocking task is surfaced (was invisible before) …
    assert len(progress["overdue_assignments"]) == 1
    assert progress["overdue_assignments"][0].template_id == mand.id
    # … and it keeps bonus locked.
    assert progress["bonus_unlocked"] is False
    # Today has no assignments, so today's required counts are zero.
    assert progress["required_total"] == 0


@pytest.mark.asyncio
async def test_no_overdue_means_bonus_unlocked(
    db_session, test_family, test_child_user
):
    progress = await TaskAssignmentService.get_daily_progress(
        db_session, user_id=test_child_user.id, family_id=test_family.id,
    )
    assert progress["overdue_assignments"] == []
    assert progress["bonus_unlocked"] is True


@pytest.mark.asyncio
async def test_completed_prior_day_mandatory_does_not_block(
    db_session, test_family, test_child_user, mandatory_template_factory
):
    mand = await mandatory_template_factory(family=test_family)
    yesterday = date.today() - timedelta(days=1)
    await _assign(
        db_session, test_family, test_child_user, mand, yesterday,
        status=AssignmentStatus.COMPLETED,
    )
    progress = await TaskAssignmentService.get_daily_progress(
        db_session, user_id=test_child_user.id, family_id=test_family.id,
    )
    assert progress["overdue_assignments"] == []
    assert progress["bonus_unlocked"] is True
