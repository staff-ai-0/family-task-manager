"""Gig modes — competition cancels siblings on claim (W4.1)."""

import pytest
from datetime import date, timedelta
from sqlalchemy import select

from app.models.task_template import TaskTemplate, GigMode
from app.models.task_assignment import TaskAssignment, AssignmentStatus
from app.services.task_assignment_service import TaskAssignmentService


async def _seed_competition_gig(db_session, family, users: list, *, mode: str = "competition"):
    tmpl = TaskTemplate(
        title="Rake leaves",
        points=30,
        effort_level=1,
        interval_days=7,
        is_bonus=True,
        gig_mode=mode,
        family_id=family.id,
    )
    db_session.add(tmpl)
    await db_session.flush()
    today = date.today()
    week_monday = today - timedelta(days=today.weekday())
    assignments = []
    for u in users:
        a = TaskAssignment(
            template_id=tmpl.id,
            assigned_to=u.id,
            family_id=family.id,
            status=AssignmentStatus.PENDING,
            assigned_date=today,
            week_of=week_monday,
        )
        db_session.add(a)
        assignments.append(a)
    await db_session.commit()
    for a in assignments:
        await db_session.refresh(a)
    return tmpl, assignments


class TestCompetitionMode:
    async def test_first_claim_cancels_siblings(
        self, db_session, test_family, test_child_user, test_teen_user
    ):
        tmpl, [a_child, a_teen] = await _seed_competition_gig(
            db_session, test_family, [test_child_user, test_teen_user]
        )
        await TaskAssignmentService.claim_gig(
            db_session, a_child.id, test_family.id, test_child_user.id
        )
        # Teen's row should be CANCELLED now.
        teen_q = select(TaskAssignment).where(TaskAssignment.id == a_teen.id)
        teen_row = (await db_session.execute(teen_q)).scalar_one()
        assert teen_row.status == AssignmentStatus.CANCELLED

    async def test_claim_mode_does_not_cancel_siblings(
        self, db_session, test_family, test_child_user, test_teen_user
    ):
        tmpl, [a_child, a_teen] = await _seed_competition_gig(
            db_session, test_family, [test_child_user, test_teen_user], mode="claim"
        )
        await TaskAssignmentService.claim_gig(
            db_session, a_child.id, test_family.id, test_child_user.id
        )
        teen_q = select(TaskAssignment).where(TaskAssignment.id == a_teen.id)
        teen_row = (await db_session.execute(teen_q)).scalar_one()
        assert teen_row.status == AssignmentStatus.PENDING

    async def test_competition_winner_stays_claimed(
        self, db_session, test_family, test_child_user, test_teen_user
    ):
        tmpl, [a_child, a_teen] = await _seed_competition_gig(
            db_session, test_family, [test_child_user, test_teen_user]
        )
        await TaskAssignmentService.claim_gig(
            db_session, a_child.id, test_family.id, test_child_user.id
        )
        child_q = select(TaskAssignment).where(TaskAssignment.id == a_child.id)
        child_row = (await db_session.execute(child_q)).scalar_one()
        assert child_row.status == AssignmentStatus.CLAIMED
