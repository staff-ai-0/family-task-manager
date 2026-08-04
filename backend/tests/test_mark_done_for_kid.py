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
idempotent on the ledger. The caller has to be told, not silently short-changed
— and then trues it up with a top-up release (see test_chore_paycheck.py).
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
from conftest import current_week_monday, family_local_today


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
    db_session, family, child, template, *, days_ago=3, on=None,
    status=AssignmentStatus.OVERDUE, approval=ApprovalStatus.NONE,
):
    d = on if on is not None else date.today() - timedelta(days=days_ago)
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
async def test_the_horizon_matches_the_window_it_claims_to_match(
    db_session, test_family, test_child_user, test_parent_user
):
    """The cut-off must be the one list_outstanding_weeks actually enforces.

    The old rule was "56 days from assigned_date"; the window is
    `range(lookback_weeks - 1, ...)` off the current MONDAY, so its oldest
    visible week is current_monday - 49 days. A chore dated 50-56 days back
    therefore passed the guard and landed in the review queue for a week the
    parent's payout screen will never list — cash that can never be released.
    Both halves are asserted against list_outstanding_weeks itself, so the two
    rules cannot drift apart again.
    """
    from app.services.bank_service import BankService

    tpl = await _chore_template(db_session, test_family)
    monday = await current_week_monday(db_session, test_family.id)
    acct = await BankService.ensure_account(db_session, test_child_user)
    acct.allowance_mode = "chore_proportional"
    acct.allowance_cents = 25000
    await db_session.commit()

    # One week older than the oldest week the payout screen can show. Dated on
    # that week's SUNDAY so it is at most 56 days from today — i.e. the old
    # assigned_date rule accepted it.
    too_old = await _assignment(
        db_session, test_family, test_child_user, tpl,
        on=monday - timedelta(days=50),
    )
    listed = {w["week_of"] for w in await BankService.list_outstanding_weeks(
        db_session, test_child_user, test_family.id
    )}
    assert too_old.week_of not in listed, "fixture is not actually out of window"
    with pytest.raises(ValidationException):
        await TaskAssignmentService.mark_done_for_kid(
            db_session, assignment_id=too_old.id, family_id=test_family.id,
            parent_id=test_parent_user.id, note="ok",
        )

    # The oldest week the payout screen DOES show is still markable.
    oldest_ok = await _assignment(
        db_session, test_family, test_child_user, tpl,
        on=monday - timedelta(days=49),
    )
    listed = {w["week_of"] for w in await BankService.list_outstanding_weeks(
        db_session, test_child_user, test_family.id
    )}
    assert oldest_ok.week_of in listed
    await TaskAssignmentService.mark_done_for_kid(
        db_session, assignment_id=oldest_ok.id, family_id=test_family.id,
        parent_id=test_parent_user.id, note="ok",
    )
    await db_session.refresh(oldest_ok)
    assert oldest_ok.approval_status == ApprovalStatus.PENDING


@pytest.mark.asyncio
async def test_a_future_dated_chore_is_rejected(
    db_session, test_family, test_child_user, test_parent_user
):
    """Tomorrow's chore cannot be "already done".

    The lookback guard only ever rejected too-OLD assignments: for a chore
    dated next week `today - assigned_date` is NEGATIVE, sails under the
    horizon, and a parent could push a chore that has not happened yet into
    the graded review queue — where approving it pays out. complete_assignment
    already refuses the same thing on the kid's side; this is the parent-side
    hole in the identical rule.
    """
    tpl = await _chore_template(db_session, test_family)
    today = await family_local_today(db_session, test_family.id)

    for offset in (1, 3, 14):
        a = await _assignment(
            db_session, test_family, test_child_user, tpl,
            on=today + timedelta(days=offset),
            status=AssignmentStatus.PENDING,
        )
        with pytest.raises(ValidationException):
            await TaskAssignmentService.mark_done_for_kid(
                db_session, assignment_id=a.id, family_id=test_family.id,
                parent_id=test_parent_user.id, note="la hará mañana",
            )
        # Untouched: it must not have entered the review queue at all.
        await db_session.refresh(a)
        assert a.status == AssignmentStatus.PENDING
        assert a.approval_status == ApprovalStatus.NONE
        assert a.completed_at is None

    # Boundary: TODAY is still allowed (the existing behaviour this must not
    # break — a chore due today that the kid forgot to tap is the main case).
    todays = await _assignment(
        db_session, test_family, test_child_user, tpl,
        on=today, status=AssignmentStatus.PENDING,
    )
    await TaskAssignmentService.mark_done_for_kid(
        db_session, assignment_id=todays.id, family_id=test_family.id,
        parent_id=test_parent_user.id, note="sí la hizo hoy",
    )
    await db_session.refresh(todays)
    assert todays.approval_status == ApprovalStatus.PENDING


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
    week_of=...), so once a week is paid a plain re-release 409s. Retroactive
    credit then yields points but no cash on its own — a silent shortfall
    unless the caller surfaces it, which is what this flag is for. The parent
    acts on it with a top_up=true release.
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


# ---------------------------------------------------------------------------
# Optional photo. A parent asserting "she did it" is more convincing with the
# evidence attached, and the approvals queue already renders proof_image_url
# with a thumbnail + lightbox, so the photo shows up where the grading happens.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_photo_is_stored_when_given(
    db_session, test_family, test_child_user, test_parent_user
):
    tpl = await _chore_template(db_session, test_family)
    a = await _assignment(db_session, test_family, test_child_user, tpl)

    # Exactly the shape POST /proof-upload returns: uuid4().hex + real ext.
    url = f"/uploads/gig-proofs/{uuid4().hex}.jpg"
    await TaskAssignmentService.mark_done_for_kid(
        db_session, assignment_id=a.id, family_id=test_family.id,
        parent_id=test_parent_user.id, note="aquí está la foto",
        proof_image_url=url,
    )
    await db_session.refresh(a)
    assert a.proof_image_url == url


@pytest.mark.asyncio
async def test_photo_is_optional(
    db_session, test_family, test_child_user, test_parent_user
):
    tpl = await _chore_template(db_session, test_family)
    a = await _assignment(db_session, test_family, test_child_user, tpl)

    await TaskAssignmentService.mark_done_for_kid(
        db_session, assignment_id=a.id, family_id=test_family.id,
        parent_id=test_parent_user.id, note="sin foto",
    )
    await db_session.refresh(a)
    assert a.proof_image_url is None


@pytest.mark.asyncio
async def test_an_arbitrary_url_is_refused(
    db_session, test_family, test_child_user, test_parent_user
):
    """Only paths this app issued.

    proof_image_url is rendered straight into an <img src> in the approvals
    queue, so accepting a client-supplied absolute URL would let a caller point
    it at any host — an off-site fetch on the grader's browser at best, and a
    javascript:/data: payload at worst. The upload endpoint returns
    /uploads/gig-proofs/<name>; nothing else is acceptable.
    """
    tpl = await _chore_template(db_session, test_family)
    a = await _assignment(db_session, test_family, test_child_user, tpl)

    for bad in (
        "https://evil.example/x.jpg",
        "//evil.example/x.jpg",
        "javascript:alert(1)",
        "data:image/png;base64,AAA",
        "/uploads/gig-proofs/../../etc/passwd",
        "/etc/passwd",
        "/uploads/other/x.jpg",
        "/uploads/gig-proofs/short.jpg",
        "/uploads/gig-proofs/" + ("a" * 32) + ".svg",
    ):
        with pytest.raises(ValidationException):
            await TaskAssignmentService.mark_done_for_kid(
                db_session, assignment_id=a.id, family_id=test_family.id,
                parent_id=test_parent_user.id, note="ok", proof_image_url=bad,
            )


@pytest.mark.asyncio
async def test_route_accepts_a_photo(
    client, auth_headers, db_session, test_family, test_child_user
):
    tpl = await _chore_template(db_session, test_family)
    a = await _assignment(db_session, test_family, test_child_user, tpl)

    r = await client.post(
        f"/api/task-assignments/{a.id}/mark-done-for-kid",
        json={"note": "con foto", "proof_image_url": "/uploads/gig-proofs/" + ("a" * 32) + ".webp"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    await db_session.refresh(a)
    assert a.proof_image_url == "/uploads/gig-proofs/" + ("a" * 32) + ".webp"


@pytest.mark.asyncio
async def test_route_refuses_an_offsite_photo(
    client, auth_headers, db_session, test_family, test_child_user
):
    tpl = await _chore_template(db_session, test_family)
    a = await _assignment(db_session, test_family, test_child_user, tpl)

    r = await client.post(
        f"/api/task-assignments/{a.id}/mark-done-for-kid",
        json={"note": "x", "proof_image_url": "https://evil.example/x.jpg"},
        headers=auth_headers,
    )
    assert r.status_code in (400, 422)
    await db_session.refresh(a)
    assert a.proof_image_url is None
