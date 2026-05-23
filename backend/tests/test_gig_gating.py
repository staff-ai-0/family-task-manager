"""Gig gating + zero-point mandatory tests."""
from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenException
from app.models.point_transaction import PointTransaction
from app.models.task_assignment import TaskAssignment, AssignmentStatus, ApprovalStatus
from app.services.task_assignment_service import TaskAssignmentService


def _monday_of(d: date) -> date:
    """Helper: return Monday of the week containing d."""
    return d - timedelta(days=d.weekday())


@pytest.mark.asyncio
async def test_local_today_returns_family_tz(db_session: AsyncSession, test_family, test_child_user):
    """Helper computes today in family timezone."""
    test_family.timezone = "America/Mexico_City"
    await db_session.commit()

    result = await TaskAssignmentService._user_local_today(db_session, test_child_user.id)

    assert isinstance(result, date)


@pytest.mark.asyncio
async def test_mandatory_completion_awards_no_points(
    db_session, test_family, test_child_user, mandatory_template_factory,
):
    template = await mandatory_template_factory(family=test_family, points=0)
    today = date.today()
    assignment = TaskAssignment(
        id=uuid4(),
        template_id=template.id,
        assigned_to=test_child_user.id,
        family_id=test_family.id,
        assigned_date=today,
        week_of=_monday_of(today),
        status=AssignmentStatus.PENDING,
    )
    db_session.add(assignment)
    await db_session.commit()

    before = test_child_user.points
    result = await TaskAssignmentService.complete_assignment(
        db_session, assignment.id, test_family.id, test_child_user.id, proof_text=None,
    )

    await db_session.refresh(test_child_user)
    assert result.status == AssignmentStatus.COMPLETED
    assert result.approval_status == ApprovalStatus.NONE
    assert test_child_user.points == before

    count = await db_session.scalar(
        select(func.count()).select_from(PointTransaction).where(PointTransaction.user_id == test_child_user.id)
    )
    assert count == 0


@pytest.mark.asyncio
async def test_gig_locked_when_mandatory_pending(
    db_session, test_family, test_child_user,
    mandatory_template_factory, gig_template_factory,
):
    mandatory = await mandatory_template_factory(family=test_family)
    gig = await gig_template_factory(family=test_family, points=20)

    today = date.today()
    monday = _monday_of(today)
    mand_assign = TaskAssignment(
        id=uuid4(), template_id=mandatory.id, assigned_to=test_child_user.id,
        family_id=test_family.id, assigned_date=today, week_of=monday,
        status=AssignmentStatus.PENDING,
    )
    gig_assign = TaskAssignment(
        id=uuid4(), template_id=gig.id, assigned_to=test_child_user.id,
        family_id=test_family.id, assigned_date=today, week_of=monday,
        status=AssignmentStatus.PENDING,
    )
    db_session.add_all([mand_assign, gig_assign])
    await db_session.commit()

    with pytest.raises(ForbiddenException, match="mandatory"):
        await TaskAssignmentService.complete_assignment(
            db_session, gig_assign.id, test_family.id, test_child_user.id,
            proof_text="did the gig",
        )


@pytest.mark.asyncio
async def test_gig_unlocked_completes_pending(
    db_session, test_family, test_child_user, gig_template_factory,
):
    gig = await gig_template_factory(family=test_family, points=20)
    today = date.today()
    assignment = TaskAssignment(
        id=uuid4(), template_id=gig.id, assigned_to=test_child_user.id,
        family_id=test_family.id, assigned_date=today, week_of=_monday_of(today),
        status=AssignmentStatus.PENDING,
    )
    db_session.add(assignment)
    await db_session.commit()

    before = test_child_user.points
    result = await TaskAssignmentService.complete_assignment(
        db_session, assignment.id, test_family.id, test_child_user.id,
        proof_text="learned about rootless podman storage",
    )
    await db_session.refresh(test_child_user)

    assert result.status == AssignmentStatus.COMPLETED
    assert result.approval_status == ApprovalStatus.PENDING
    assert result.proof_text == "learned about rootless podman storage"
    assert test_child_user.points == before  # not yet credited


@pytest.mark.asyncio
async def test_list_marks_gigs_locked_when_mandatory_pending(
    db_session, test_family, test_child_user,
    mandatory_template_factory, gig_template_factory,
):
    mand = await mandatory_template_factory(family=test_family)
    gig = await gig_template_factory(family=test_family, points=20)
    today = date.today()
    week_of = today - timedelta(days=today.weekday())
    db_session.add_all([
        TaskAssignment(
            id=uuid4(), template_id=mand.id, assigned_to=test_child_user.id,
            family_id=test_family.id, assigned_date=today, week_of=week_of,
            status=AssignmentStatus.PENDING,
        ),
        TaskAssignment(
            id=uuid4(), template_id=gig.id, assigned_to=test_child_user.id,
            family_id=test_family.id, assigned_date=today, week_of=week_of,
            status=AssignmentStatus.PENDING,
        ),
    ])
    await db_session.commit()

    rows = await TaskAssignmentService.list_for_user_today_with_locks(
        db_session, test_child_user.id, test_family.id
    )

    locked = [r for r in rows if r["is_locked"]]
    assert len(locked) == 1
    assert locked[0]["is_bonus"] is True


@pytest.mark.asyncio
async def test_carry_over_overdue_mandatory_blocks_today_gig(
    db_session, test_family, test_child_user,
    mandatory_template_factory, gig_template_factory,
):
    """An OVERDUE mandatory from yesterday should block today's gigs."""
    mand = await mandatory_template_factory(family=test_family)
    gig = await gig_template_factory(family=test_family, points=20)
    today = date.today()
    yesterday = today - timedelta(days=1)
    week_of = today - timedelta(days=today.weekday())

    db_session.add_all([
        # Yesterday's mandatory left OVERDUE
        TaskAssignment(
            id=uuid4(), template_id=mand.id, assigned_to=test_child_user.id,
            family_id=test_family.id, assigned_date=yesterday, week_of=week_of,
            status=AssignmentStatus.OVERDUE,
        ),
        # Today's gig (no pending mandatory today)
        gig_assignment := TaskAssignment(
            id=uuid4(), template_id=gig.id, assigned_to=test_child_user.id,
            family_id=test_family.id, assigned_date=today, week_of=week_of,
            status=AssignmentStatus.PENDING,
        ),
    ])
    await db_session.commit()

    with pytest.raises(ForbiddenException, match="mandatory"):
        await TaskAssignmentService.complete_assignment(
            db_session, gig_assignment.id, test_family.id, test_child_user.id,
            proof_text="trying to skip",
        )


@pytest.mark.asyncio
async def test_carry_over_pending_from_yesterday_blocks_today_gig(
    db_session, test_family, test_child_user,
    mandatory_template_factory, gig_template_factory,
):
    """A still-PENDING mandatory from yesterday should also block."""
    mand = await mandatory_template_factory(family=test_family)
    gig = await gig_template_factory(family=test_family, points=20)
    today = date.today()
    yesterday = today - timedelta(days=1)
    week_of = today - timedelta(days=today.weekday())

    db_session.add_all([
        TaskAssignment(
            id=uuid4(), template_id=mand.id, assigned_to=test_child_user.id,
            family_id=test_family.id, assigned_date=yesterday, week_of=week_of,
            status=AssignmentStatus.PENDING,
        ),
        gig_assignment := TaskAssignment(
            id=uuid4(), template_id=gig.id, assigned_to=test_child_user.id,
            family_id=test_family.id, assigned_date=today, week_of=week_of,
            status=AssignmentStatus.PENDING,
        ),
    ])
    await db_session.commit()

    has_open = await TaskAssignmentService.has_open_mandatory_through(
        db_session, test_child_user.id, test_family.id, today
    )
    assert has_open is True

    with pytest.raises(ForbiddenException):
        await TaskAssignmentService.complete_assignment(
            db_session, gig_assignment.id, test_family.id, test_child_user.id,
            proof_text="trying again",
        )


@pytest.mark.asyncio
async def test_cancelled_mandatory_does_not_block(
    db_session, test_family, test_child_user,
    mandatory_template_factory, gig_template_factory,
):
    """CANCELLED mandatory (parent waived) does not block gigs."""
    mand = await mandatory_template_factory(family=test_family)
    gig = await gig_template_factory(family=test_family, points=20)
    today = date.today()
    yesterday = today - timedelta(days=1)
    week_of = today - timedelta(days=today.weekday())

    db_session.add_all([
        TaskAssignment(
            id=uuid4(), template_id=mand.id, assigned_to=test_child_user.id,
            family_id=test_family.id, assigned_date=yesterday, week_of=week_of,
            status=AssignmentStatus.CANCELLED,
        ),
        gig_assignment := TaskAssignment(
            id=uuid4(), template_id=gig.id, assigned_to=test_child_user.id,
            family_id=test_family.id, assigned_date=today, week_of=week_of,
            status=AssignmentStatus.PENDING,
        ),
    ])
    await db_session.commit()

    has_open = await TaskAssignmentService.has_open_mandatory_through(
        db_session, test_child_user.id, test_family.id, today
    )
    assert has_open is False

    result = await TaskAssignmentService.complete_assignment(
        db_session, gig_assignment.id, test_family.id, test_child_user.id,
        proof_text="cancelled mandatory didn't block",
    )
    assert result.approval_status == ApprovalStatus.PENDING


@pytest.mark.asyncio
async def test_progress_bonus_unlocked_respects_carry_over(
    db_session, test_family, test_child_user,
    mandatory_template_factory, gig_template_factory,
):
    """get_daily_progress.bonus_unlocked must be False when overdue mandatory exists."""
    mand = await mandatory_template_factory(family=test_family)
    gig = await gig_template_factory(family=test_family, points=20)
    today = date.today()
    yesterday = today - timedelta(days=1)
    week_of = today - timedelta(days=today.weekday())

    db_session.add_all([
        TaskAssignment(
            id=uuid4(), template_id=mand.id, assigned_to=test_child_user.id,
            family_id=test_family.id, assigned_date=yesterday, week_of=week_of,
            status=AssignmentStatus.OVERDUE,
        ),
        TaskAssignment(
            id=uuid4(), template_id=gig.id, assigned_to=test_child_user.id,
            family_id=test_family.id, assigned_date=today, week_of=week_of,
            status=AssignmentStatus.PENDING,
        ),
    ])
    await db_session.commit()

    progress = await TaskAssignmentService.get_daily_progress(
        db_session, test_child_user.id, test_family.id, today,
    )
    assert progress["bonus_unlocked"] is False
    # No mandatory on `today` itself
    assert progress["required_total"] == 0
    assert progress["bonus_total"] == 1
