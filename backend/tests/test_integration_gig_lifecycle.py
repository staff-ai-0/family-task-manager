"""End-to-end gig lifecycle (W7.6).

Walks the full path:
  1. parent creates a gig template
  2. child completes the gig with proof_text + proof_image_url
  3. AI photo validator returns high score → auto-approve
  4. points awarded, PointTransaction created
  5. user balance incremented
  6. notification persisted
"""

import pytest
from datetime import date, timedelta
from unittest.mock import AsyncMock
from sqlalchemy import select

from app.models.notification import Notification, NotificationType
from app.models.point_transaction import PointTransaction, TransactionType
from app.models.task_assignment import (
    TaskAssignment,
    AssignmentStatus,
    ApprovalStatus,
)
from app.models.task_template import TaskTemplate
from app.services.task_assignment_service import TaskAssignmentService


async def _seed_gig(db, family, child):
    tmpl = TaskTemplate(
        title="Vacuum living room",
        points=20,
        effort_level=2,  # ×1.5 → 30 effective
        interval_days=7,
        is_bonus=True,
        family_id=family.id,
    )
    db.add(tmpl)
    await db.flush()
    today = date.today()
    week_monday = today - timedelta(days=today.weekday())
    a = TaskAssignment(
        template_id=tmpl.id,
        assigned_to=child.id,
        family_id=family.id,
        status=AssignmentStatus.PENDING,
        assigned_date=today,
        week_of=week_monday,
    )
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return tmpl, a


class TestGigLifecycleAIAutoApproval:
    async def test_high_ai_score_auto_approves_and_credits(
        self, db_session, test_family, test_child_user, plus_subscription, monkeypatch
    ):
        # AI photo validation is paid-only (ai_features) — see test_ai_gating.
        # Force trust streak below threshold so AI is the gate.
        test_child_user.gig_trust_streak = 0
        test_child_user.points = 0
        # AI photo validation requires the family's parental opt-in.
        test_family.ai_processing_consent = True
        await db_session.commit()

        tmpl, a = await _seed_gig(db_session, test_family, test_child_user)
        before = test_child_user.points

        # Mock vision validator → high score, beats GIG_AI_AUTO_APPROVE_THRESHOLD
        async def fake_validate(url, title, description=None):
            from app.services.task_proof_validator import ProofValidation
            return ProofValidation(
                score=0.95,
                explanation="Clearly shows vacuumed carpet.",
            )

        monkeypatch.setattr(
            "app.services.task_assignment_service.validate_proof_photo"
            if False  # the import is dynamic; patch the module instead
            else "app.services.task_proof_validator.validate_proof_photo",
            fake_validate,
        )

        result = await TaskAssignmentService.complete_assignment(
            db_session,
            a.id,
            test_family.id,
            test_child_user.id,
            proof_text="vacuumed",
            proof_image_url="/uploads/gig-proofs/synthetic.jpg",
        )

        assert result.approval_status == ApprovalStatus.APPROVED
        assert result.ai_validation_score == pytest.approx(0.95)
        assert "vacuumed carpet" in (result.ai_validation_notes or "")

        # Refresh child + assert points
        await db_session.refresh(test_child_user)
        # effort_level=2 → effective 30; collab=N/A → award_per_completer=30
        assert test_child_user.points == before + 30
        assert test_child_user.gig_trust_streak == 1

        # PointTransaction row created
        tx = (
            await db_session.execute(
                select(PointTransaction).where(
                    PointTransaction.user_id == test_child_user.id
                )
            )
        ).scalars().all()
        assert len(tx) == 1
        assert tx[0].points == 30

        # Notification created for child
        notifs = (
            await db_session.execute(
                select(Notification).where(
                    Notification.user_id == test_child_user.id,
                    Notification.type == NotificationType.GIG_APPROVED,
                )
            )
        ).scalars().all()
        assert len(notifs) >= 1

    async def test_low_ai_score_goes_to_manual_review(
        self, db_session, test_family, test_child_user, plus_subscription, monkeypatch
    ):
        test_child_user.gig_trust_streak = 0
        test_child_user.points = 0
        # AI photo validation requires the family's parental opt-in.
        test_family.ai_processing_consent = True
        await db_session.commit()
        tmpl, a = await _seed_gig(db_session, test_family, test_child_user)

        async def fake_validate(url, title, description=None):
            from app.services.task_proof_validator import ProofValidation
            return ProofValidation(score=0.2, explanation="Unclear photo.")

        monkeypatch.setattr(
            "app.services.task_proof_validator.validate_proof_photo",
            fake_validate,
        )

        result = await TaskAssignmentService.complete_assignment(
            db_session,
            a.id,
            test_family.id,
            test_child_user.id,
            proof_text="did it",
            proof_image_url="/uploads/gig-proofs/synthetic.jpg",
        )

        assert result.approval_status == ApprovalStatus.PENDING
        assert result.ai_validation_score == pytest.approx(0.2)
        # No points awarded yet
        await db_session.refresh(test_child_user)
        assert test_child_user.points == 0

    async def test_no_image_no_ai_path(
        self, db_session, test_family, test_child_user
    ):
        test_child_user.gig_trust_streak = 0
        test_child_user.points = 0
        await db_session.commit()
        tmpl, a = await _seed_gig(db_session, test_family, test_child_user)

        result = await TaskAssignmentService.complete_assignment(
            db_session,
            a.id,
            test_family.id,
            test_child_user.id,
            proof_text="done",
            proof_image_url=None,
        )
        assert result.approval_status == ApprovalStatus.PENDING
        assert result.ai_validation_score is None
