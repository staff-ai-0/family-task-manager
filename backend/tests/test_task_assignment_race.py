"""Concurrency / double-award + single-winner protection for TaskAssignment gigs."""
import asyncio
from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.task_assignment import TaskAssignment, AssignmentStatus, ApprovalStatus
from app.models.point_transaction import PointTransaction
from app.services.task_assignment_service import TaskAssignmentService
from app.core.exceptions import ValidationException, ForbiddenException


def _monday_of(d):
    return d - timedelta(days=d.weekday())


async def _pending_approval(db, family, child, template):
    today = date.today()
    a = TaskAssignment(
        id=uuid4(), template_id=template.id, assigned_to=child.id,
        family_id=family.id, assigned_date=today, week_of=_monday_of(today),
        status=AssignmentStatus.COMPLETED,
        approval_status=ApprovalStatus.PENDING,
        proof_text="did the thing",
    )
    db.add(a)
    await db.commit()
    return a


@pytest.mark.asyncio
async def test_concurrent_approve_gig_awards_points_once(
    test_engine, db_session, test_family, test_parent_user, test_child_user,
    gig_template_factory,
):
    gig = await gig_template_factory(family=test_family, points=25)
    assignment = await _pending_approval(db_session, test_family, test_child_user, gig)
    assignment_id = assignment.id
    points_before = test_child_user.points

    maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async def _approve():
        async with maker() as s:
            return await TaskAssignmentService.approve_gig(
                s, assignment_id, test_family.id, test_parent_user.id,
                approve=True, notes=None,
            )

    results = await asyncio.gather(_approve(), _approve(), return_exceptions=True)

    succeeded = [r for r in results if isinstance(r, TaskAssignment)]
    failed = [r for r in results if isinstance(r, Exception)]
    assert len(succeeded) == 1, f"expected 1 success, got {results}"
    assert len(failed) == 1 and isinstance(failed[0], ValidationException), (
        f"expected 1 ValidationException, got {results}"
    )

    txn_count = await db_session.scalar(
        select(func.count())
        .select_from(PointTransaction)
        .where(PointTransaction.assignment_id == assignment_id)
    )
    assert txn_count == 1, f"double-award: {txn_count} point transactions"

    await db_session.refresh(test_child_user)
    assert test_child_user.points == points_before + 25


async def _competition_template(db, family, points=20):
    from app.models.task_template import TaskTemplate, AssignmentType

    t = TaskTemplate(
        id=uuid4(), title="Race to finish", points=points, interval_days=7,
        assignment_type=AssignmentType.AUTO, is_bonus=True, is_active=True,
        gig_mode="competition", family_id=family.id,
    )
    db.add(t)
    await db.commit()
    return t


async def _pending_gig(db, family, user, template, week):
    a = TaskAssignment(
        id=uuid4(), template_id=template.id, assigned_to=user.id,
        family_id=family.id, assigned_date=week, week_of=week,
        status=AssignmentStatus.PENDING,
    )
    db.add(a)
    await db.commit()
    return a


@pytest.mark.asyncio
async def test_competition_claim_single_winner(
    test_engine, db_session, test_family, test_child_user, test_teen_user,
):
    """Competition mode is 'first claim wins'. Two kids claiming their own
    sibling assignments at the same time must yield exactly ONE CLAIMED winner."""
    week = _monday_of(date.today())
    tmpl = await _competition_template(db_session, test_family)
    a_child = await _pending_gig(db_session, test_family, test_child_user, tmpl, week)
    a_teen = await _pending_gig(db_session, test_family, test_teen_user, tmpl, week)

    maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async def _claim(aid, uid):
        async with maker() as s:
            return await TaskAssignmentService.claim_gig(s, aid, test_family.id, uid)

    results = await asyncio.gather(
        _claim(a_child.id, test_child_user.id),
        _claim(a_teen.id, test_teen_user.id),
        return_exceptions=True,
    )

    claimed_count = await db_session.scalar(
        select(func.count())
        .select_from(TaskAssignment)
        .where(
            TaskAssignment.template_id == tmpl.id,
            TaskAssignment.week_of == week,
            TaskAssignment.status == AssignmentStatus.CLAIMED,
        )
    )
    assert claimed_count == 1, (
        f"competition must have ONE winner, got {claimed_count}; results={results}"
    )
