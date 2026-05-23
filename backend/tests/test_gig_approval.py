"""Gig approval flow."""
from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, func

from app.models.task_assignment import TaskAssignment, AssignmentStatus, ApprovalStatus
from app.models.point_transaction import PointTransaction, TransactionType
from app.services.task_assignment_service import TaskAssignmentService
from app.core.exceptions import ForbiddenException, ValidationException


def _monday_of(d):
    return d - timedelta(days=d.weekday())


async def _make_pending_gig(db_session, family, child, template):
    today = date.today()
    assignment = TaskAssignment(
        id=uuid4(), template_id=template.id, assigned_to=child.id,
        family_id=family.id, assigned_date=today, week_of=_monday_of(today),
        status=AssignmentStatus.COMPLETED,
        approval_status=ApprovalStatus.PENDING,
        proof_text="did the thing",
    )
    db_session.add(assignment)
    await db_session.commit()
    return assignment


@pytest.mark.asyncio
async def test_parent_approves_gig_credits_points(
    db_session, test_family, test_parent_user, test_child_user, gig_template_factory,
):
    gig = await gig_template_factory(family=test_family, points=25)
    assignment = await _make_pending_gig(db_session, test_family, test_child_user, gig)
    before = test_child_user.points

    await TaskAssignmentService.approve_gig(
        db_session, assignment.id, test_family.id, test_parent_user.id,
        approve=True, notes="great writeup",
    )

    await db_session.refresh(test_child_user)
    await db_session.refresh(assignment)
    assert assignment.approval_status == ApprovalStatus.APPROVED
    assert test_child_user.points == before + 25

    txn = await db_session.scalar(
        select(PointTransaction).where(PointTransaction.user_id == test_child_user.id)
    )
    assert txn.type == TransactionType.GIG_APPROVED
    assert txn.points == 25


@pytest.mark.asyncio
async def test_parent_rejects_gig_no_credit(
    db_session, test_family, test_parent_user, test_child_user, gig_template_factory,
):
    gig = await gig_template_factory(family=test_family, points=25)
    assignment = await _make_pending_gig(db_session, test_family, test_child_user, gig)
    before = test_child_user.points

    await TaskAssignmentService.approve_gig(
        db_session, assignment.id, test_family.id, test_parent_user.id,
        approve=False, notes="no proof of conclusions",
    )
    await db_session.refresh(test_child_user)
    await db_session.refresh(assignment)
    assert assignment.approval_status == ApprovalStatus.REJECTED
    assert test_child_user.points == before
    count = await db_session.scalar(select(func.count()).select_from(PointTransaction))
    assert count == 0


@pytest.mark.asyncio
async def test_non_parent_cannot_approve(
    db_session, test_family, test_child_user, test_teen_user, gig_template_factory,
):
    gig = await gig_template_factory(family=test_family, points=25)
    assignment = await _make_pending_gig(db_session, test_family, test_child_user, gig)

    with pytest.raises(ForbiddenException):
        await TaskAssignmentService.approve_gig(
            db_session, assignment.id, test_family.id, test_teen_user.id,
            approve=True, notes=None,
        )


@pytest.mark.asyncio
async def test_double_approve_conflicts(
    db_session, test_family, test_parent_user, test_child_user, gig_template_factory,
):
    gig = await gig_template_factory(family=test_family, points=25)
    assignment = await _make_pending_gig(db_session, test_family, test_child_user, gig)

    await TaskAssignmentService.approve_gig(
        db_session, assignment.id, test_family.id, test_parent_user.id,
        approve=True, notes=None,
    )
    with pytest.raises(ValidationException, match="already"):
        await TaskAssignmentService.approve_gig(
            db_session, assignment.id, test_family.id, test_parent_user.id,
            approve=True, notes=None,
        )


@pytest.mark.asyncio
async def test_list_pending_approvals_family_scoped(
    db_session, test_family, test_child_user, gig_template_factory,
):
    gig = await gig_template_factory(family=test_family, points=10)
    await _make_pending_gig(db_session, test_family, test_child_user, gig)

    rows = await TaskAssignmentService.list_pending_approvals(db_session, test_family.id)
    assert len(rows) == 1
    assert rows[0].approval_status == ApprovalStatus.PENDING
