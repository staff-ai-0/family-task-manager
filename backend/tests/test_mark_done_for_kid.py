"""Parent marks an overdue chore done on the kid's behalf.

The parent grid (/parent/assignments) could reschedule or cancel a past chore
but never say "she actually did this". The edit modal offered only
pending/cancelled, and nothing set approval_status=PENDING except kid-side
completion — so an overdue task could not reach the graded-review queue at all.

This does NOT award points. It puts the task into the existing graded path
(approve_gig) so grade scaling, metering, streak and the point transaction stay
on one code path. The tests below pin that, plus the money edge that makes this
more than a dropdown change: on a week whose paycheck was already released,
retroactive credit gives POINTS but no cash, because release_chore_paycheck is
idempotent on the ledger. The caller has to be told, not silently short-changed.
"""
from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.exceptions import (
    ForbiddenException,
    NotFoundException,
    ValidationException,
)
from app.models.task_assignment import (
    TaskAssignment,
    AssignmentStatus,
    ApprovalStatus,
)
from app.models.point_transaction import PointTransaction
from app.services.task_assignment_service import TaskAssignmentService


def _monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


async def _chore_template(db_session, family, points=20):
    from app.models.task_template import TaskTemplate, AssignmentType

    t = TaskTemplate(
        id=uuid4(), title="Barrer escaleras", points=points, interval_days=1,
        assignment_type=AssignmentType.AUTO, is_bonus=False, is_active=True,
        family_id=family.id,
    )
    db_session.add(t)
    await db_session.commit()
    return t


async def _assignment(
    db_session, family, child, template, *, days_ago=3,
    status=AssignmentStatus.OVERDUE, approval=ApprovalStatus.NONE,
):
    d = date.today() - timedelta(days=days_ago)
    a = TaskAssignment(
        id=uuid4(), template_id=template.id, assigned_to=child.id,
        family_id=family.id, assigned_date=d, week_of=_monday_of(d),
        status=status, approval_status=approval,
    )
    db_session.add(a)
    await db_session.commit()
    return a


@pytest.mark.asyncio
async def test_marks_overdue_into_the_review_queue_without_awarding(
    db_session, test_family, test_child_user, test_parent_user
):
    tpl = await _chore_template(db_session, test_family)
    a = await _assignment(db_session, test_family, test_child_user, tpl)
    points_before = test_child_user.points

    await TaskAssignmentService.mark_done_for_kid(
        db_session, assignment_id=a.id, family_id=test_family.id,
        parent_id=test_parent_user.id, note="La hizo, olvidé marcarla",
    )
    await db_session.refresh(a)

    assert a.status == AssignmentStatus.COMPLETED
    assert a.approval_status == ApprovalStatus.PENDING
    assert a.completed_at is not None
    # The whole point: this step credits nothing. Grading does.
    await db_session.refresh(test_child_user)
    assert test_child_user.points == points_before
    ledger = (await db_session.execute(
        select(PointTransaction).where(PointTransaction.user_id == test_child_user.id)
    )).scalars().all()
    assert ledger == []


@pytest.mark.asyncio
async def test_the_week_it_was_due_is_preserved(
    db_session, test_family, test_child_user, test_parent_user
):
    # _chore_units and the family cup both scope on week_of, so credit must
    # land on the week the chore was DUE, not the week it was marked.
    tpl = await _chore_template(db_session, test_family)
    a = await _assignment(db_session, test_family, test_child_user, tpl, days_ago=9)
    original_week = a.week_of
    original_date = a.assigned_date

    await TaskAssignmentService.mark_done_for_kid(
        db_session, assignment_id=a.id, family_id=test_family.id,
        parent_id=test_parent_user.id, note="sí la hizo",
    )
    await db_session.refresh(a)

    assert a.week_of == original_week
    assert a.assigned_date == original_date


@pytest.mark.asyncio
async def test_a_note_is_required(
    db_session, test_family, test_child_user, test_parent_user
):
    # approval_notes surfaces to the kid; a retroactive completion with no
    # explanation is confusing on their side.
    tpl = await _chore_template(db_session, test_family)
    a = await _assignment(db_session, test_family, test_child_user, tpl)

    for bad in ("", "   ", None):
        with pytest.raises(ValidationException):
            await TaskAssignmentService.mark_done_for_kid(
                db_session, assignment_id=a.id, family_id=test_family.id,
                parent_id=test_parent_user.id, note=bad,
            )


@pytest.mark.asyncio
async def test_pending_today_is_allowed_but_completed_is_not(
    db_session, test_family, test_child_user, test_parent_user
):
    tpl = await _chore_template(db_session, test_family)

    still_pending = await _assignment(
        db_session, test_family, test_child_user, tpl,
        days_ago=0, status=AssignmentStatus.PENDING,
    )
    await TaskAssignmentService.mark_done_for_kid(
        db_session, assignment_id=still_pending.id, family_id=test_family.id,
        parent_id=test_parent_user.id, note="ok",
    )

    # Already completed: points may already be awarded and the approval is
    # graded, so re-opening it in place would desync the ledger.
    done = await _assignment(
        db_session, test_family, test_child_user, tpl,
        status=AssignmentStatus.COMPLETED, approval=ApprovalStatus.APPROVED,
    )
    with pytest.raises(ValidationException):
        await TaskAssignmentService.mark_done_for_kid(
            db_session, assignment_id=done.id, family_id=test_family.id,
            parent_id=test_parent_user.id, note="ok",
        )


@pytest.mark.asyncio
async def test_cancelled_is_rejected(
    db_session, test_family, test_child_user, test_parent_user
):
    # A parent waived this chore; reviving it through this door would skip the
    # explicit un-cancel the edit modal already offers.
    tpl = await _chore_template(db_session, test_family)
    a = await _assignment(
        db_session, test_family, test_child_user, tpl,
        status=AssignmentStatus.CANCELLED,
    )
    with pytest.raises(ValidationException):
        await TaskAssignmentService.mark_done_for_kid(
            db_session, assignment_id=a.id, family_id=test_family.id,
            parent_id=test_parent_user.id, note="ok",
        )


@pytest.mark.asyncio
async def test_beyond_the_lookback_window_is_rejected(
    db_session, test_family, test_child_user, test_parent_user
):
    # Reuses list_outstanding_weeks' 8-week horizon rather than inventing a
    # second rule; a months-old chore should not suddenly pay out.
    tpl = await _chore_template(db_session, test_family)
    a = await _assignment(db_session, test_family, test_child_user, tpl, days_ago=70)
    with pytest.raises(ValidationException):
        await TaskAssignmentService.mark_done_for_kid(
            db_session, assignment_id=a.id, family_id=test_family.id,
            parent_id=test_parent_user.id, note="ok",
        )


@pytest.mark.asyncio
async def test_only_a_parent_of_that_family(
    db_session, test_family, test_child_user, test_parent_user, other_parent
):
    tpl = await _chore_template(db_session, test_family)
    a = await _assignment(db_session, test_family, test_child_user, tpl)

    # A kid cannot mark their own work done — that is the whole approval gate.
    with pytest.raises((ForbiddenException, ValidationException)):
        await TaskAssignmentService.mark_done_for_kid(
            db_session, assignment_id=a.id, family_id=test_family.id,
            parent_id=test_child_user.id, note="yo la hice",
        )

    # A parent from another family must not reach across tenants. This is a
    # NotFound rather than Forbidden on purpose: the family-scoped lookup
    # refuses to confirm that an assignment exists in someone else's family.
    with pytest.raises(NotFoundException):
        await TaskAssignmentService.mark_done_for_kid(
            db_session, assignment_id=a.id, family_id=other_parent.family_id,
            parent_id=other_parent.id, note="ok",
        )


@pytest.mark.asyncio
async def test_reports_whether_that_week_was_already_paid(
    db_session, test_family, test_child_user, test_parent_user
):
    """The money edge, and the reason this is not a dropdown change.

    release_chore_paycheck is idempotent on a CashTransaction(ALLOWANCE,
    week_of=...), so once a week is paid it cannot be topped up. Retroactive
    credit then yields points but no cash — a silent shortfall unless the
    caller surfaces it, which is what this flag is for.
    """
    from app.models.cash_transaction import CashTransaction, CashTransactionType

    tpl = await _chore_template(db_session, test_family)
    a = await _assignment(db_session, test_family, test_child_user, tpl)

    unpaid = await TaskAssignmentService.mark_done_for_kid(
        db_session, assignment_id=a.id, family_id=test_family.id,
        parent_id=test_parent_user.id, note="ok",
    )
    assert unpaid["week_already_paid"] is False

    # Now pay that week and repeat on a second assignment in the same week.
    db_session.add(CashTransaction(
        id=uuid4(), family_id=test_family.id, user_id=test_child_user.id,
        type=CashTransactionType.ALLOWANCE, amount_cents=5000,
        balance_after=5000, week_of=a.week_of, description="domingo",
    ))
    await db_session.commit()

    b = await _assignment(db_session, test_family, test_child_user, tpl)
    paid = await TaskAssignmentService.mark_done_for_kid(
        db_session, assignment_id=b.id, family_id=test_family.id,
        parent_id=test_parent_user.id, note="ok",
    )
    assert paid["week_already_paid"] is True
    # It still goes through — the parent decides, but informed.
    await db_session.refresh(b)
    assert b.approval_status == ApprovalStatus.PENDING


# ---------------------------------------------------------------------------
# HTTP layer. The service tests above call the method directly, which bypasses
# require_parent_role and the request schema — so the route's own gates need
# their own coverage.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_marks_done_and_reports_the_paid_week(
    client, auth_headers, db_session, test_family, test_child_user
):
    tpl = await _chore_template(db_session, test_family)
    a = await _assignment(db_session, test_family, test_child_user, tpl)

    r = await client.post(
        f"/api/task-assignments/{a.id}/mark-done-for-kid",
        json={"note": "la hizo el lunes"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["assignment_id"] == str(a.id)
    assert body["week_already_paid"] is False


@pytest.mark.asyncio
async def test_route_rejects_an_empty_note(
    client, auth_headers, db_session, test_family, test_child_user
):
    tpl = await _chore_template(db_session, test_family)
    a = await _assignment(db_session, test_family, test_child_user, tpl)

    r = await client.post(
        f"/api/task-assignments/{a.id}/mark-done-for-kid",
        json={"note": ""},
        headers=auth_headers,
    )
    assert r.status_code in (400, 422)


@pytest.mark.asyncio
async def test_route_is_parent_only(
    client, db_session, test_family, test_child_user, test_parent_user
):
    """A kid must not be able to mark their own work done — that is the gate."""
    tpl = await _chore_template(db_session, test_family)
    a = await _assignment(db_session, test_family, test_child_user, tpl)

    login = await client.post(
        "/api/auth/login",
        json={"email": "child@test.com", "password": "password123"},
    )
    kid_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    r = await client.post(
        f"/api/task-assignments/{a.id}/mark-done-for-kid",
        json={"note": "yo la hice"},
        headers=kid_headers,
    )
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_route_requires_auth(client, db_session, test_family, test_child_user):
    tpl = await _chore_template(db_session, test_family)
    a = await _assignment(db_session, test_family, test_child_user, tpl)

    r = await client.post(
        f"/api/task-assignments/{a.id}/mark-done-for-kid",
        json={"note": "x"},
    )
    assert r.status_code in (401, 403)
