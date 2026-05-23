"""Tests for the gig claim/unclaim workflow."""
from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenException, ValidationException
from app.models.task_assignment import (
    TaskAssignment,
    AssignmentStatus,
    ApprovalStatus,
)
from app.services.task_assignment_service import TaskAssignmentService


def _week_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


async def _make_pending(db, family, user, template, when: date | None = None):
    when = when or date.today()
    a = TaskAssignment(
        id=uuid4(), template_id=template.id, assigned_to=user.id,
        family_id=family.id, assigned_date=when, week_of=_week_of(when),
        status=AssignmentStatus.PENDING,
    )
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return a


@pytest.mark.asyncio
async def test_claim_happy_path(
    db_session: AsyncSession, test_family, test_child_user, gig_template_factory,
):
    gig = await gig_template_factory(family=test_family, points=20)
    a = await _make_pending(db_session, test_family, test_child_user, gig)

    result = await TaskAssignmentService.claim_gig(
        db_session, a.id, test_family.id, test_child_user.id,
    )
    assert result.status == AssignmentStatus.CLAIMED
    assert result.claimed_at is not None


@pytest.mark.asyncio
async def test_claim_mandatory_rejected(
    db_session, test_family, test_child_user, mandatory_template_factory,
):
    mand = await mandatory_template_factory(family=test_family)
    a = await _make_pending(db_session, test_family, test_child_user, mand)

    with pytest.raises(ValidationException, match="gigs"):
        await TaskAssignmentService.claim_gig(
            db_session, a.id, test_family.id, test_child_user.id,
        )


@pytest.mark.asyncio
async def test_claim_blocked_by_open_mandatory(
    db_session, test_family, test_child_user,
    mandatory_template_factory, gig_template_factory,
):
    mand = await mandatory_template_factory(family=test_family)
    gig = await gig_template_factory(family=test_family, points=20)
    await _make_pending(db_session, test_family, test_child_user, mand)
    gig_a = await _make_pending(db_session, test_family, test_child_user, gig)

    with pytest.raises(ForbiddenException, match="mandatory"):
        await TaskAssignmentService.claim_gig(
            db_session, gig_a.id, test_family.id, test_child_user.id,
        )


@pytest.mark.asyncio
async def test_claim_by_non_assignee_rejected(
    db_session, test_family, test_child_user, test_teen_user, gig_template_factory,
):
    gig = await gig_template_factory(family=test_family, points=20)
    a = await _make_pending(db_session, test_family, test_child_user, gig)

    with pytest.raises(ForbiddenException, match="assigned"):
        await TaskAssignmentService.claim_gig(
            db_session, a.id, test_family.id, test_teen_user.id,
        )


@pytest.mark.asyncio
async def test_double_claim_rejected(
    db_session, test_family, test_child_user, gig_template_factory,
):
    gig = await gig_template_factory(family=test_family, points=20)
    a = await _make_pending(db_session, test_family, test_child_user, gig)

    await TaskAssignmentService.claim_gig(
        db_session, a.id, test_family.id, test_child_user.id,
    )
    with pytest.raises(ValidationException, match="status"):
        await TaskAssignmentService.claim_gig(
            db_session, a.id, test_family.id, test_child_user.id,
        )


@pytest.mark.asyncio
async def test_unclaim_returns_to_pending(
    db_session, test_family, test_child_user, gig_template_factory,
):
    gig = await gig_template_factory(family=test_family, points=20)
    a = await _make_pending(db_session, test_family, test_child_user, gig)
    await TaskAssignmentService.claim_gig(
        db_session, a.id, test_family.id, test_child_user.id,
    )

    result = await TaskAssignmentService.unclaim_gig(
        db_session, a.id, test_family.id, test_child_user.id,
    )
    assert result.status == AssignmentStatus.PENDING
    assert result.claimed_at is None


@pytest.mark.asyncio
async def test_complete_works_from_claimed_state(
    db_session, test_family, test_child_user, gig_template_factory,
):
    """can_complete must accept CLAIMED, not just PENDING/OVERDUE."""
    gig = await gig_template_factory(family=test_family, points=20)
    a = await _make_pending(db_session, test_family, test_child_user, gig)
    await TaskAssignmentService.claim_gig(
        db_session, a.id, test_family.id, test_child_user.id,
    )

    result = await TaskAssignmentService.complete_assignment(
        db_session, a.id, test_family.id, test_child_user.id,
        proof_text="finished the claimed gig",
    )
    assert result.status == AssignmentStatus.COMPLETED
    assert result.approval_status == ApprovalStatus.PENDING
