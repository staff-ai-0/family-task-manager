"""Grade-credit rounding: one formula, award path and dashboard agree.

The two used to disagree at the .5 boundary — the award path rounded half-up
(25 pts × 50% = 13) while the parent payouts dashboard used Python's round(),
which is banker's rounding (12). These pin the boundary in both places.
"""
from datetime import timedelta
from uuid import uuid4

import pytest

from app.core.grading import (
    grade_credit_points,
    grade_credit_units,
    units_to_points,
)
from app.models.task_assignment import (
    ApprovalStatus,
    AssignmentStatus,
    TaskAssignment,
)
from app.models.task_template import AssignmentType, TaskTemplate
from app.services.bank_service import BankService
from app.services.task_assignment_service import TaskAssignmentService


# ── the helper itself ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "points,expected",
    # Every one of these lands exactly on .5, where banker's rounding would
    # pick the even neighbour (2, 8, 12, 18) and short the kid a point.
    [(5, 3), (15, 8), (25, 13), (35, 18)],
)
def test_half_credit_rounds_half_up(points, expected):
    assert grade_credit_points(points, 50) == expected


def test_units_carry_the_x100_scale():
    assert grade_credit_units(25, 50) == 1250
    assert units_to_points(1250) == 13
    assert grade_credit_points(25, 50) == units_to_points(grade_credit_units(25, 50))


def test_full_and_zero_credit_are_exact():
    assert grade_credit_points(25, 100) == 25
    assert grade_credit_points(25, 0) == 0
    assert units_to_points(0) == 0


def test_units_sum_before_rounding():
    # Two half-graded 25-pt chores are 25 points together, not 26 — the whole
    # reason the paycheck math sums in units and collapses once at the end.
    total = grade_credit_units(25, 50) * 2
    assert units_to_points(total) == 25


# ── award path vs. payouts dashboard ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_dashboard_matches_points_actually_awarded(
    db_session, test_family, test_parent_user, test_teen_user,
):
    """A 25-pt chore graded 50% credits 13 points; the dashboard must say 13."""
    today = await BankService._family_local_today(db_session, test_family.id)
    week = BankService._week_monday(today)

    template = TaskTemplate(
        id=uuid4(), title="Trastes", points=25, effort_level=1, interval_days=1,
        assignment_type=AssignmentType.AUTO, is_bonus=False, is_active=True,
        requires_proof=True, family_id=test_family.id,
        created_by=test_parent_user.id,
    )
    db_session.add(template)
    await db_session.flush()
    assignment = TaskAssignment(
        id=uuid4(), template_id=template.id, assigned_to=test_teen_user.id,
        family_id=test_family.id, assigned_date=today, week_of=week,
        status=AssignmentStatus.COMPLETED,
        approval_status=ApprovalStatus.PENDING, proof_text="listo",
    )
    db_session.add(assignment)
    await db_session.commit()

    before = test_teen_user.points
    await TaskAssignmentService.approve_gig(
        db_session, assignment.id, test_family.id, test_parent_user.id,
        approve=True, grade="partial", partial_credit_pct=50,
    )
    await db_session.refresh(test_teen_user)
    awarded = test_teen_user.points - before
    assert awarded == 13

    tasks = await BankService._chore_week_tasks(
        db_session, test_family.id, test_teen_user.id, week
    )
    assert len(tasks) == 1
    assert tasks[0]["status"] == "credited"
    assert tasks[0]["earned_points"] == awarded

    done_u, assigned_u, _ = await BankService._chore_units(
        db_session, test_family.id, test_teen_user.id, week
    )
    assert units_to_points(done_u) == awarded
    assert units_to_points(assigned_u) == 25


@pytest.mark.asyncio
async def test_paycheck_preview_done_points_matches_detail_rows(
    db_session, test_family, test_parent_user, test_teen_user,
):
    """The aggregate meter and the per-task list are the same number."""
    today = await BankService._family_local_today(db_session, test_family.id)
    week = BankService._week_monday(today)

    for i, (points, pct) in enumerate(((25, 50), (15, 50))):
        template = TaskTemplate(
            id=uuid4(), title=f"Tarea {i}", points=points, effort_level=1,
            interval_days=1, assignment_type=AssignmentType.AUTO,
            is_bonus=False, is_active=True, family_id=test_family.id,
            created_by=test_parent_user.id,
        )
        db_session.add(template)
        await db_session.flush()
        db_session.add(TaskAssignment(
            id=uuid4(), template_id=template.id, assigned_to=test_teen_user.id,
            family_id=test_family.id, assigned_date=week + timedelta(days=i),
            week_of=week, status=AssignmentStatus.COMPLETED,
            approval_status=ApprovalStatus.APPROVED,
            completion_grade="partial", partial_credit_pct=pct,
        ))
    await db_session.commit()

    preview = await BankService.chore_paycheck_preview(
        db_session, test_teen_user, test_family.id
    )
    tasks = await BankService._chore_week_tasks(
        db_session, test_family.id, test_teen_user.id, week
    )
    # 12.5 + 7.5 = 20 in units; per-row half-up gives 13 + 8 = 21. The
    # aggregate rounds once, so it is 20 — the rows must still each match
    # what the review credited.
    assert preview["done_points"] == 20
    assert [t["earned_points"] for t in tasks] == [13, 8]
