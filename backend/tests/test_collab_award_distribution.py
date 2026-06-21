"""M11 integration: collaboration awards distribute the remainder across
completers (by approval order) so the pot is conserved — verified against the
real DB prior-approved-sibling count that `_award_for` uses."""
from datetime import date
from uuid import uuid4

import pytest

from app.models.task_assignment import (
    TaskAssignment,
    AssignmentStatus,
    ApprovalStatus,
)
from app.services.task_assignment_service import TaskAssignmentService


@pytest.mark.asyncio
async def test_collaboration_award_distributes_remainder(
    db_session, test_family, test_parent_user, test_child_user
):
    from tests.test_task_assignment_service import _create_template

    tmpl = await _create_template(
        db_session, test_family.id, test_parent_user.id,
        title="Collab", is_bonus=True, points=10, effort_level=1,
        gig_mode="collaboration", collaboration_min_count=3,
    )
    assert tmpl.effective_points == 10  # 10 / 3 -> floor 3 lost 1 before M11

    week = date(2026, 6, 22)
    rows = []
    for _ in range(3):
        a = TaskAssignment(
            id=uuid4(), template_id=tmpl.id, assigned_to=test_child_user.id,
            family_id=test_family.id, assigned_date=week, week_of=week,
            status=AssignmentStatus.COMPLETED,
            approval_status=ApprovalStatus.PENDING,
        )
        db_session.add(a)
        rows.append(a)
    await db_session.commit()

    awards = []
    for a in rows:
        # Mirror the service: the row is APPROVED before its award is computed.
        a.approval_status = ApprovalStatus.APPROVED
        await db_session.commit()
        awards.append(await TaskAssignmentService._award_for(db_session, a, tmpl))

    assert sorted(awards, reverse=True) == [4, 3, 3]
    assert sum(awards) == 10  # pot conserved — no points lost


@pytest.mark.asyncio
async def test_daily_collaboration_conserves_each_date_independently(
    db_session, test_family, test_parent_user, test_child_user
):
    """A daily collaboration gig has one row per member per date, all sharing
    one week_of. Each date's pot must be conserved on its own — scoping the
    ordinal by week_of (instead of assigned_date) would conflate the days and
    drop the remainder on every date after the first."""
    from tests.test_task_assignment_service import _create_template

    tmpl = await _create_template(
        db_session, test_family.id, test_parent_user.id,
        title="DailyCollab", is_bonus=True, points=10, effort_level=1,
        gig_mode="collaboration", collaboration_min_count=3,
    )

    week = date(2026, 6, 22)            # Monday
    dates = [week, date(2026, 6, 23)]   # same week_of, two instances
    rows_by_date = {}
    for d in dates:
        rows = []
        for _ in range(3):
            a = TaskAssignment(
                id=uuid4(), template_id=tmpl.id, assigned_to=test_child_user.id,
                family_id=test_family.id, assigned_date=d, week_of=week,
                status=AssignmentStatus.COMPLETED,
                approval_status=ApprovalStatus.PENDING,
            )
            db_session.add(a)
            rows.append(a)
        rows_by_date[d] = rows
    await db_session.commit()

    # Interleave approvals across the two dates to stress the per-instance scope.
    awards_by_date = {d: [] for d in dates}
    for i in range(3):
        for d in dates:
            a = rows_by_date[d][i]
            a.approval_status = ApprovalStatus.APPROVED
            await db_session.commit()
            awards_by_date[d].append(
                await TaskAssignmentService._award_for(db_session, a, tmpl)
            )

    for d in dates:
        assert sorted(awards_by_date[d], reverse=True) == [4, 3, 3], d
        assert sum(awards_by_date[d]) == 10, d  # each date conserves its own pot
