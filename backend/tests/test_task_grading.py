"""Graded parent review: full / partial / missed + partial-credit scaling."""
from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models.point_transaction import PointTransaction
from app.models.task_assignment import TaskAssignment, AssignmentStatus, ApprovalStatus
from app.services.task_assignment_service import TaskAssignmentService
from app.core.exceptions import ValidationException


def _monday_of(d):
    return d - timedelta(days=d.weekday())


async def _make_pending(db_session, family, child, template):
    today = date.today()
    assignment = TaskAssignment(
        id=uuid4(), template_id=template.id, assigned_to=child.id,
        family_id=family.id, assigned_date=today, week_of=_monday_of(today),
        status=AssignmentStatus.COMPLETED,
        approval_status=ApprovalStatus.PENDING,
        proof_text="done",
    )
    db_session.add(assignment)
    await db_session.commit()
    return assignment


async def _make_chore_template(db_session, family, points=20):
    from app.models.task_template import TaskTemplate, AssignmentType

    t = TaskTemplate(
        id=uuid4(), title="Trastes", points=points, interval_days=7,
        assignment_type=AssignmentType.AUTO, is_bonus=False, is_active=True,
        requires_proof=True, family_id=family.id,
    )
    db_session.add(t)
    await db_session.commit()
    return t


async def _make_collab_template(db_session, family, points=30):
    from app.models.task_template import TaskTemplate, AssignmentType

    t = TaskTemplate(
        id=uuid4(), title="Garage", points=points, interval_days=7,
        assignment_type=AssignmentType.AUTO, is_bonus=True, is_active=True,
        gig_mode="collaboration", collaboration_min_count=2, family_id=family.id,
    )
    db_session.add(t)
    await db_session.commit()
    return t


@pytest.mark.asyncio
async def test_approve_without_grade_defaults_full(
    db_session, test_family, test_parent_user, test_child_user, gig_template_factory,
):
    gig = await gig_template_factory(family=test_family, points=25)
    a = await _make_pending(db_session, test_family, test_child_user, gig)
    before = test_child_user.points

    await TaskAssignmentService.approve_gig(
        db_session, a.id, test_family.id, test_parent_user.id, approve=True,
    )
    await db_session.refresh(test_child_user)
    await db_session.refresh(a)
    assert test_child_user.points == before + 25
    assert a.completion_grade == "full"
    assert a.partial_credit_pct is None


@pytest.mark.asyncio
async def test_partial_defaults_to_50_pct_half_up(
    db_session, test_family, test_parent_user, test_child_user, gig_template_factory,
):
    gig = await gig_template_factory(family=test_family, points=25)
    a = await _make_pending(db_session, test_family, test_child_user, gig)
    before = test_child_user.points

    await TaskAssignmentService.approve_gig(
        db_session, a.id, test_family.id, test_parent_user.id,
        approve=True, grade="partial", notes="dobla mejor las camisas",
    )
    await db_session.refresh(test_child_user)
    await db_session.refresh(a)
    # 25 × 50% = 12.5 → 13 (integer half-up)
    assert test_child_user.points == before + 13
    assert a.completion_grade == "partial"
    assert a.partial_credit_pct == 50
    assert a.approval_status == ApprovalStatus.APPROVED
    assert a.approval_notes == "dobla mejor las camisas"


@pytest.mark.asyncio
async def test_partial_custom_pct_scales_chore_points(
    db_session, test_family, test_parent_user, test_child_user,
):
    chore = await _make_chore_template(db_session, test_family, points=20)
    a = await _make_pending(db_session, test_family, test_child_user, chore)
    before = test_child_user.points

    await TaskAssignmentService.approve_gig(
        db_session, a.id, test_family.id, test_parent_user.id,
        approve=True, grade="partial", partial_credit_pct=25,
    )
    await db_session.refresh(test_child_user)
    await db_session.refresh(a)
    assert test_child_user.points == before + 5  # 20 × 25%
    assert a.partial_credit_pct == 25
    # chore stays completed+approved
    assert a.status == AssignmentStatus.COMPLETED
    assert a.approval_status == ApprovalStatus.APPROVED


@pytest.mark.asyncio
async def test_missed_zero_credit_resets_streak_and_reopens_chore(
    db_session, test_family, test_parent_user, test_child_user, gig_template_factory,
):
    # bonus gig: streak resets
    gig = await gig_template_factory(family=test_family, points=25)
    ga = await _make_pending(db_session, test_family, test_child_user, gig)
    test_child_user.gig_trust_streak = 3
    await db_session.commit()

    await TaskAssignmentService.approve_gig(
        db_session, ga.id, test_family.id, test_parent_user.id,
        approve=False, grade="missed", notes="no se hizo",
    )
    await db_session.refresh(test_child_user)
    await db_session.refresh(ga)
    assert ga.completion_grade == "missed"
    assert ga.approval_status == ApprovalStatus.REJECTED
    assert test_child_user.gig_trust_streak == 0

    # chore: re-opened for redo
    chore = await _make_chore_template(db_session, test_family, points=10)
    ca = await _make_pending(db_session, test_family, test_child_user, chore)
    await TaskAssignmentService.approve_gig(
        db_session, ca.id, test_family.id, test_parent_user.id,
        approve=False, grade="missed",
    )
    await db_session.refresh(ca)
    assert ca.completion_grade == "missed"
    assert ca.status == AssignmentStatus.PENDING

    count = await db_session.scalar(
        select(PointTransaction).where(PointTransaction.user_id == test_child_user.id)
    )
    assert count is None  # no credit anywhere


@pytest.mark.asyncio
async def test_legacy_reject_keeps_grade_null(
    db_session, test_family, test_parent_user, test_child_user, gig_template_factory,
):
    gig = await gig_template_factory(family=test_family, points=25)
    a = await _make_pending(db_session, test_family, test_child_user, gig)

    await TaskAssignmentService.approve_gig(
        db_session, a.id, test_family.id, test_parent_user.id, approve=False,
    )
    await db_session.refresh(a)
    assert a.approval_status == ApprovalStatus.REJECTED
    assert a.completion_grade is None
    assert a.partial_credit_pct is None


@pytest.mark.asyncio
async def test_partial_rejected_on_collaboration(
    db_session, test_family, test_parent_user, test_child_user,
):
    collab = await _make_collab_template(db_session, test_family, points=30)
    a = await _make_pending(db_session, test_family, test_child_user, collab)

    with pytest.raises(ValidationException, match="collaboration"):
        await TaskAssignmentService.approve_gig(
            db_session, a.id, test_family.id, test_parent_user.id,
            approve=True, grade="partial",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [0, 100, -5, 150])
async def test_partial_pct_must_be_1_to_99(
    db_session, test_family, test_parent_user, test_child_user, gig_template_factory, bad,
):
    gig = await gig_template_factory(family=test_family, points=25)
    a = await _make_pending(db_session, test_family, test_child_user, gig)

    with pytest.raises(ValidationException, match="partial"):
        await TaskAssignmentService.approve_gig(
            db_session, a.id, test_family.id, test_parent_user.id,
            approve=True, grade="partial", partial_credit_pct=bad,
        )


@pytest.mark.asyncio
async def test_reopen_clears_stale_grade(
    db_session, test_family, test_parent_user, test_child_user,
):
    """Parent re-opens a graded chore via patch: the stale partial grade must
    be wiped with the rest of the decision trail — otherwise the redo would
    silently pay partial credit in the payday math without a fresh review."""
    chore = await _make_chore_template(db_session, test_family, points=20)
    a = await _make_pending(db_session, test_family, test_child_user, chore)
    await TaskAssignmentService.approve_gig(
        db_session, a.id, test_family.id, test_parent_user.id,
        approve=True, grade="partial", partial_credit_pct=50,
    )
    await db_session.refresh(a)
    assert a.partial_credit_pct == 50

    await TaskAssignmentService.patch_assignment(
        db_session, a.id, test_family.id, status=AssignmentStatus.PENDING,
    )
    await db_session.refresh(a)
    assert a.status == AssignmentStatus.PENDING
    assert a.completion_grade is None
    assert a.partial_credit_pct is None
    assert a.approval_status == ApprovalStatus.NONE


@pytest.mark.asyncio
async def test_approve_route_accepts_grade_and_echoes_it(
    client, auth_headers, db_session, test_family, test_child_user, gig_template_factory,
):
    gig = await gig_template_factory(family=test_family, points=25)
    a = await _make_pending(db_session, test_family, test_child_user, gig)

    r = await client.post(
        f"/api/task-assignments/{a.id}/approve",
        json={"approve": True, "grade": "partial", "partial_credit_pct": 75,
              "notes": "casi perfecto"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["completion_grade"] == "partial"
    assert body["partial_credit_pct"] == 75
    assert body["approval_notes"] == "casi perfecto"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "approve,grade", [(True, "missed"), (False, "full"), (False, "partial"), (True, "bogus")]
)
async def test_contradictory_grade_combinations_rejected(
    db_session, test_family, test_parent_user, test_child_user, gig_template_factory,
    approve, grade,
):
    gig = await gig_template_factory(family=test_family, points=25)
    a = await _make_pending(db_session, test_family, test_child_user, gig)

    with pytest.raises(ValidationException):
        await TaskAssignmentService.approve_gig(
            db_session, a.id, test_family.id, test_parent_user.id,
            approve=approve, grade=grade,
        )
