"""
OversightService — read-only aggregations for the parent command center.

Per-kid summary cards and a unified pending-approval queue spanning both
review systems (legacy task-assignment gigs + new gig board). Approve/reject
actions stay on their existing endpoints; this service never mutates.
"""
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.consequence import Consequence
from app.models.gig import GigClaim, GigClaimStatus
from app.models.task_assignment import (
    ApprovalStatus,
    AssignmentStatus,
    TaskAssignment,
)
from app.models.user import User, UserRole
from app.schemas.oversight import (
    KidGoal,
    KidSummary,
    OversightSummary,
    PendingApprovalItem,
    PendingCounts,
)
from app.services.reward_goal_service import RewardGoalService
from app.services.task_assignment_service import TaskAssignmentService

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class OversightService:

    @staticmethod
    async def get_summary(db: AsyncSession, family_id: UUID) -> OversightSummary:
        """Per-kid cards + unified pending counts. Six fixed queries, no N+1."""
        kids = list(
            (
                await db.execute(
                    select(User)
                    .where(
                        User.family_id == family_id,
                        User.role.in_([UserRole.CHILD, UserRole.TEEN]),
                        User.is_active.is_(True),
                    )
                    .order_by(User.name)
                )
            ).scalars().all()
        )

        task_counts = dict(
            (
                await db.execute(
                    select(TaskAssignment.assigned_to, func.count())
                    .where(
                        TaskAssignment.family_id == family_id,
                        TaskAssignment.approval_status == ApprovalStatus.PENDING,
                    )
                    .group_by(TaskAssignment.assigned_to)
                )
            ).all()
        )

        claim_counts = dict(
            (
                await db.execute(
                    select(GigClaim.claimed_by, func.count())
                    .where(
                        GigClaim.family_id == family_id,
                        GigClaim.status == GigClaimStatus.COMPLETED,
                    )
                    .group_by(GigClaim.claimed_by)
                )
            ).all()
        )

        consequence_counts = dict(
            (
                await db.execute(
                    select(Consequence.applied_to_user, func.count())
                    .where(
                        Consequence.family_id == family_id,
                        Consequence.active.is_(True),
                    )
                    .group_by(Consequence.applied_to_user)
                )
            ).all()
        )

        today = await TaskAssignmentService._family_local_today(db, family_id)
        open_today_counts = dict(
            (
                await db.execute(
                    select(TaskAssignment.assigned_to, func.count())
                    .where(
                        TaskAssignment.family_id == family_id,
                        TaskAssignment.status == AssignmentStatus.PENDING,
                        TaskAssignment.assigned_date == today,
                    )
                    .group_by(TaskAssignment.assigned_to)
                )
            ).all()
        )

        goals = await RewardGoalService.get_family_goals(family_id, db)

        threshold = max(1, settings.GIG_AUTO_APPROVE_STREAK)
        members: list[KidSummary] = []
        for kid in kids:
            gp = goals.get(kid.id)
            streak = int(kid.gig_trust_streak or 0)
            members.append(
                KidSummary(
                    user_id=kid.id,
                    name=kid.name,
                    role=kid.role.value if hasattr(kid.role, "value") else str(kid.role),
                    points=int(kid.points or 0),
                    gig_trust_streak=streak,
                    auto_approve_active=streak >= threshold,
                    goal=KidGoal(
                        reward_title=gp.reward_title,
                        reward_icon=gp.reward_icon,
                        progress_pct=gp.progress_pct,
                        pts_to_go=gp.pts_to_go,
                        affordable=gp.affordable,
                    )
                    if gp
                    else None,
                    pending_approvals=int(task_counts.get(kid.id, 0))
                    + int(claim_counts.get(kid.id, 0)),
                    open_today=int(open_today_counts.get(kid.id, 0)),
                    active_consequences=int(consequence_counts.get(kid.id, 0)),
                )
            )

        total_tasks = sum(int(v) for v in task_counts.values())
        total_claims = sum(int(v) for v in claim_counts.values())
        return OversightSummary(
            members=members,
            pending_counts=PendingCounts(
                tasks=total_tasks,
                gig_claims=total_claims,
                total=total_tasks + total_claims,
            ),
        )

    @staticmethod
    async def get_pending_approvals(
        db: AsyncSession, family_id: UUID
    ) -> list[PendingApprovalItem]:
        """Normalized union of both review queues, sorted by completed_at asc."""
        from app.services.gig_claim_service import GigClaimService

        rows = await TaskAssignmentService.list_pending_approvals(db, family_id)
        user_ids = list({r.assigned_to for r in rows})
        user_names: dict = {}
        if user_ids:
            q = select(User.id, User.name).where(User.id.in_(user_ids))
            user_names = {uid: name for uid, name in (await db.execute(q)).all()}

        items = [
            PendingApprovalItem(
                kind="task",
                id=r.id,
                title=r.template.title if r.template else "",
                kid_id=r.assigned_to,
                kid_name=user_names.get(r.assigned_to, ""),
                points=int(
                    r.template.award_points_per_completer if r.template else 0
                ),
                completed_at=r.completed_at,
                proof_text=r.proof_text,
                proof_image_url=r.proof_image_url,
                ai_score=r.ai_validation_score,
            )
            for r in rows
        ]

        claims = await GigClaimService.get_pending_approvals(db, family_id)
        for item in claims:
            c = item["claim"]
            items.append(
                PendingApprovalItem(
                    kind="gig_claim",
                    id=c.id,
                    title=item["gig_title"],
                    kid_id=c.claimed_by,
                    kid_name=item["claimer_name"],
                    points=int(item["gig_points"] or 0),
                    completed_at=c.completed_at,
                    proof_text=c.proof_text,
                    proof_image_url=c.proof_image_url,
                    ai_score=None,
                )
            )

        items.sort(key=lambda i: (i.completed_at is None, i.completed_at or _EPOCH))
        return items
