"""M11 / review-#54: collaboration gigs re-split the pot among the ACTUAL
number of completers (not collaboration_min_count). Each approval re-divides
the pot and reconciles earlier completers (top-up or claw-back), so the total
awarded always equals the pot — for any number of completers, including more
than min_count — and a daily gig settles each date independently."""
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import select, func

from app.models.task_assignment import (
    TaskAssignment,
    AssignmentStatus,
    ApprovalStatus,
)
from app.models.point_transaction import PointTransaction, TransactionType
from app.models.task_template import TaskTemplate
from app.models.user import User, UserRole
from app.services.task_assignment_service import TaskAssignmentService


async def _net(db, assignment_id) -> int:
    """Net points credited to a completer for one assignment (award + reconciles)."""
    return int(
        (
            await db.execute(
                select(func.coalesce(func.sum(PointTransaction.points), 0)).where(
                    PointTransaction.assignment_id == assignment_id,
                    PointTransaction.type == TransactionType.GIG_APPROVED,
                )
            )
        ).scalar()
        or 0
    )


async def _make_children(db, family_id, n):
    kids = []
    for i in range(n):
        u = User(
            email=f"collab{i}@test.com", password_hash="x", name=f"Kid{i}",
            role=UserRole.CHILD, family_id=family_id, points=0,
        )
        db.add(u)
        kids.append(u)
    await db.commit()
    for u in kids:
        await db.refresh(u)
    return kids


@pytest.mark.asyncio
async def test_collaboration_resplits_among_actual_completers(
    db_session, test_family, test_parent_user
):
    from tests.test_task_assignment_service import _create_template

    tmpl = await _create_template(
        db_session, test_family.id, test_parent_user.id,
        title="Collab", is_bonus=True, points=10, effort_level=1,
        gig_mode="collaboration", collaboration_min_count=3,
    )
    assert tmpl.effective_points == 10

    kids = await _make_children(db_session, test_family.id, 4)
    d = date(2026, 6, 22)
    rows = []
    for kid in kids:
        a = TaskAssignment(
            id=uuid4(), template_id=tmpl.id, assigned_to=kid.id,
            family_id=test_family.id, assigned_date=d, week_of=d,
            status=AssignmentStatus.COMPLETED, approval_status=ApprovalStatus.PENDING,
        )
        db_session.add(a)
        rows.append(a)
    await db_session.commit()

    # Approve one at a time; after each, the pot is re-split among the approved
    # set and the total always equals the pot — even past min_count (the old
    # fixed-min_count split over-distributed: 4 completers summed 4+3+3+3=13).
    for k, a in enumerate(rows, start=1):
        a.approval_status = ApprovalStatus.APPROVED
        await db_session.commit()
        await TaskAssignmentService._settle_collaboration(db_session, a, tmpl)
        await db_session.commit()

        nets = [await _net(db_session, r.id) for r in rows[:k]]
        assert sum(nets) == 10, f"pot not conserved at {k} completers: {nets}"
        assert sorted(nets) == sorted(
            TaskTemplate.distribute_points(10, k)
        ), f"shares wrong at {k}: {nets}"


@pytest.mark.asyncio
async def test_daily_collaboration_settles_each_date_independently(
    db_session, test_family, test_parent_user
):
    """A daily collaboration gig has one row per member per date sharing one
    week_of; each date's pot must settle on its own (scoped by assigned_date)."""
    from tests.test_task_assignment_service import _create_template

    tmpl = await _create_template(
        db_session, test_family.id, test_parent_user.id,
        title="DailyCollab", is_bonus=True, points=10, effort_level=1,
        gig_mode="collaboration", collaboration_min_count=3,
    )
    kids = await _make_children(db_session, test_family.id, 3)
    week = date(2026, 6, 22)
    dates = [week, date(2026, 6, 23)]  # same week_of, two instances
    rows_by_date = {}
    for dt in dates:
        rows = []
        for kid in kids:
            a = TaskAssignment(
                id=uuid4(), template_id=tmpl.id, assigned_to=kid.id,
                family_id=test_family.id, assigned_date=dt, week_of=week,
                status=AssignmentStatus.COMPLETED,
                approval_status=ApprovalStatus.PENDING,
            )
            db_session.add(a)
            rows.append(a)
        rows_by_date[dt] = rows
    await db_session.commit()

    for i in range(3):
        for dt in dates:
            a = rows_by_date[dt][i]
            a.approval_status = ApprovalStatus.APPROVED
            await db_session.commit()
            await TaskAssignmentService._settle_collaboration(db_session, a, tmpl)
            await db_session.commit()

    for dt in dates:
        nets = [await _net(db_session, r.id) for r in rows_by_date[dt]]
        assert sorted(nets, reverse=True) == [4, 3, 3], (dt, nets)
        assert sum(nets) == 10, (dt, nets)  # each date conserves its own pot
