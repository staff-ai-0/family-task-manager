"""Auto-post task/gig completions into family chat (P2 — Campfire liveliness).

When a task/gig is completed-and-credited or parent-approved, a celebratory
card is posted into the shared family chat thread (reaction-ready, carrying the
proof photo when one is present). Rejections do NOT post.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select

from app.models.family_chat import FamilyChatMessage
from app.models.task_assignment import (
    ApprovalStatus,
    AssignmentStatus,
    TaskAssignment,
)
from app.models.task_template import AssignmentType, TaskTemplate
from app.services.task_assignment_service import TaskAssignmentService


def _monday(d):
    return d - timedelta(days=d.weekday())


async def _template(db, family_id, *, points, is_bonus=False, requires_proof=False):
    t = TaskTemplate(
        id=uuid4(),
        title="Lavar los platos",
        points=points,
        interval_days=1 if not is_bonus else 7,
        assignment_type=AssignmentType.AUTO,
        is_bonus=is_bonus,
        is_active=True,
        requires_proof=requires_proof,
        family_id=family_id,
    )
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return t


async def _chat_messages(db, family_id):
    return (
        await db.execute(
            select(FamilyChatMessage)
            .where(FamilyChatMessage.family_id == family_id)
            .order_by(FamilyChatMessage.created_at.asc())
        )
    ).scalars().all()


async def test_mandatory_completion_autoposts_card(
    db_session, test_family, test_child_user
):
    """A silently-completed mandatory chore posts a completion card to chat."""
    tmpl = await _template(db_session, test_family.id, points=10)
    today = datetime.now(timezone.utc).date()
    a = TaskAssignment(
        id=uuid4(),
        template_id=tmpl.id,
        assigned_to=test_child_user.id,
        family_id=test_family.id,
        assigned_date=today,
        week_of=_monday(today),
        status=AssignmentStatus.PENDING,
    )
    db_session.add(a)
    await db_session.commit()

    assert await _chat_messages(db_session, test_family.id) == []

    await TaskAssignmentService.complete_assignment(
        db_session, a.id, test_family.id, test_child_user.id
    )

    msgs = await _chat_messages(db_session, test_family.id)
    assert len(msgs) == 1
    body = msgs[0].body
    assert test_child_user.name in body
    assert "Lavar los platos" in body
    assert msgs[0].image_url is None  # silent chore has no proof photo


async def test_approved_proof_chore_autoposts_with_photo(
    db_session, test_family, test_child_user, test_parent_user
):
    """A proof-required chore posts its card WITH the photo, on approval."""
    tmpl = await _template(
        db_session, test_family.id, points=15, requires_proof=True
    )
    today = datetime.now(timezone.utc).date()
    a = TaskAssignment(
        id=uuid4(),
        template_id=tmpl.id,
        assigned_to=test_child_user.id,
        family_id=test_family.id,
        assigned_date=today,
        week_of=_monday(today),
        status=AssignmentStatus.PENDING,
    )
    db_session.add(a)
    await db_session.commit()

    proof = "/uploads/gig-proofs/proof.jpg"
    # Completing a proof-required chore parks it for review → no card yet.
    await TaskAssignmentService.complete_assignment(
        db_session, a.id, test_family.id, test_child_user.id, proof_image_url=proof
    )
    assert await _chat_messages(db_session, test_family.id) == []

    # Parent approves → the card posts, carrying the proof photo.
    await TaskAssignmentService.approve_gig(
        db_session, a.id, test_family.id, test_parent_user.id, approve=True
    )

    msgs = await _chat_messages(db_session, test_family.id)
    assert len(msgs) == 1
    assert test_child_user.name in msgs[0].body
    assert msgs[0].image_url == proof


async def test_rejected_completion_does_not_autopost(
    db_session, test_family, test_child_user, test_parent_user
):
    """A rejected completion is NOT celebrated — no chat card is posted."""
    tmpl = await _template(
        db_session, test_family.id, points=15, requires_proof=True
    )
    today = datetime.now(timezone.utc).date()
    a = TaskAssignment(
        id=uuid4(),
        template_id=tmpl.id,
        assigned_to=test_child_user.id,
        family_id=test_family.id,
        assigned_date=today,
        week_of=_monday(today),
        status=AssignmentStatus.PENDING,
    )
    db_session.add(a)
    await db_session.commit()

    await TaskAssignmentService.complete_assignment(
        db_session,
        a.id,
        test_family.id,
        test_child_user.id,
        proof_image_url="/uploads/gig-proofs/proof.jpg",
    )
    await TaskAssignmentService.approve_gig(
        db_session, a.id, test_family.id, test_parent_user.id, approve=False,
        notes="redo it",
    )

    assert await _chat_messages(db_session, test_family.id) == []
