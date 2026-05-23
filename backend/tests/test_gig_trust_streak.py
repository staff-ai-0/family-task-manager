"""Tests for trust-score auto-approval of gigs."""
from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.point_transaction import PointTransaction, TransactionType
from app.models.task_assignment import (
    TaskAssignment,
    AssignmentStatus,
    ApprovalStatus,
)
from app.services.task_assignment_service import TaskAssignmentService


def _week_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


async def _new_gig_assignment(db, family, user, template):
    today = date.today()
    a = TaskAssignment(
        id=uuid4(), template_id=template.id, assigned_to=user.id,
        family_id=family.id, assigned_date=today, week_of=_week_of(today),
        status=AssignmentStatus.PENDING,
    )
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return a


@pytest.mark.asyncio
async def test_below_threshold_enters_pending(
    db_session: AsyncSession, test_family, test_child_user, gig_template_factory,
):
    """A user with streak < threshold still requires parent approval."""
    assert test_child_user.gig_trust_streak == 0  # default
    gig = await gig_template_factory(family=test_family, points=25)
    a = await _new_gig_assignment(db_session, test_family, test_child_user, gig)
    before = test_child_user.points

    result = await TaskAssignmentService.complete_assignment(
        db_session, a.id, test_family.id, test_child_user.id,
        proof_text="first gig",
    )
    await db_session.refresh(test_child_user)

    assert result.approval_status == ApprovalStatus.PENDING
    assert test_child_user.points == before  # not yet credited
    assert test_child_user.gig_trust_streak == 0


@pytest.mark.asyncio
async def test_at_threshold_auto_approves(
    db_session, test_family, test_child_user, gig_template_factory,
):
    """Once streak hits threshold, completion auto-approves and credits."""
    test_child_user.gig_trust_streak = settings.GIG_AUTO_APPROVE_STREAK
    await db_session.commit()

    gig = await gig_template_factory(family=test_family, points=30)
    a = await _new_gig_assignment(db_session, test_family, test_child_user, gig)
    before = test_child_user.points

    result = await TaskAssignmentService.complete_assignment(
        db_session, a.id, test_family.id, test_child_user.id,
        proof_text="auto-approved gig",
    )
    await db_session.refresh(test_child_user)

    assert result.approval_status == ApprovalStatus.APPROVED
    assert result.approval_notes == "Auto-approved via trust streak"
    assert test_child_user.points == before + 30
    assert test_child_user.gig_trust_streak == settings.GIG_AUTO_APPROVE_STREAK + 1

    txn = await db_session.scalar(
        select(PointTransaction).where(PointTransaction.user_id == test_child_user.id)
    )
    assert txn.type == TransactionType.GIG_APPROVED
    assert txn.points == 30


@pytest.mark.asyncio
async def test_manual_approve_increments_streak(
    db_session, test_family, test_parent_user, test_child_user, gig_template_factory,
):
    """Parent approval bumps the streak so the child graduates toward auto-approve."""
    gig = await gig_template_factory(family=test_family, points=20)
    a = await _new_gig_assignment(db_session, test_family, test_child_user, gig)
    # Submit
    await TaskAssignmentService.complete_assignment(
        db_session, a.id, test_family.id, test_child_user.id,
        proof_text="need a parent decision",
    )

    await TaskAssignmentService.approve_gig(
        db_session, a.id, test_family.id, test_parent_user.id,
        approve=True, notes=None,
    )
    await db_session.refresh(test_child_user)

    assert test_child_user.gig_trust_streak == 1


@pytest.mark.asyncio
async def test_reject_resets_streak(
    db_session, test_family, test_parent_user, test_child_user, gig_template_factory,
):
    """A parent rejection sends the streak back to zero."""
    test_child_user.gig_trust_streak = 5
    await db_session.commit()

    gig = await gig_template_factory(family=test_family, points=20)
    a = await _new_gig_assignment(db_session, test_family, test_child_user, gig)

    # Force PENDING (otherwise streak=5 auto-approves on completion)
    a.status = AssignmentStatus.COMPLETED
    a.approval_status = ApprovalStatus.PENDING
    a.proof_text = "needs review"
    await db_session.commit()

    await TaskAssignmentService.approve_gig(
        db_session, a.id, test_family.id, test_parent_user.id,
        approve=False, notes="not good enough",
    )
    await db_session.refresh(test_child_user)

    assert test_child_user.gig_trust_streak == 0


@pytest.mark.asyncio
async def test_auto_approve_skips_pending_email(
    db_session, test_family, test_child_user, gig_template_factory, monkeypatch,
):
    """Auto-approved gigs must not fire the parent-pending email."""
    test_child_user.gig_trust_streak = settings.GIG_AUTO_APPROVE_STREAK
    await db_session.commit()

    called = []

    async def fake_notify(db, **kwargs):
        called.append(kwargs)

    from app.services.email_service import EmailService
    monkeypatch.setattr(EmailService, "notify_parents_gig_pending", fake_notify)

    gig = await gig_template_factory(family=test_family, points=25)
    a = await _new_gig_assignment(db_session, test_family, test_child_user, gig)

    await TaskAssignmentService.complete_assignment(
        db_session, a.id, test_family.id, test_child_user.id,
        proof_text="silent auto-approve",
    )

    assert called == []
