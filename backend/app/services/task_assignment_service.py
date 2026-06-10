"""
TaskAssignment Service

Business logic for task assignments, weekly shuffle, completion, and bonus gating.
"""

import random
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, delete as sql_delete
from sqlalchemy.orm import selectinload
from typing import List, Optional
from datetime import datetime, date, timedelta, timezone
from uuid import UUID

from app.models.task_template import TaskTemplate, AssignmentType
from app.models.task_assignment import TaskAssignment, AssignmentStatus, ApprovalStatus
from app.models.user import User
from app.models.point_transaction import PointTransaction, TransactionType
from app.core.exceptions import (
    NotFoundException,
    ForbiddenException,
    ValidationException,
)
from app.services.base_service import (
    BaseFamilyService,
    verify_user_in_family,
    get_user_by_id,
)


class TaskAssignmentService(BaseFamilyService[TaskAssignment]):
    """Service for task assignment operations including shuffle and gating"""

    model = TaskAssignment

    @staticmethod
    async def _user_local_today(db: AsyncSession, user_id: UUID) -> date:
        """Return today's date in the user's family timezone."""
        from zoneinfo import ZoneInfo
        from app.models.family import Family
        from app.services.base_service import get_user_by_id
        user = await get_user_by_id(db, user_id)
        tz_name = "UTC"
        if user.family_id is not None:
            family = await db.get(Family, user.family_id)
            if family and family.timezone:
                tz_name = family.timezone
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = ZoneInfo("UTC")
        return datetime.now(tz).date()

    # ─── Shuffle Algorithm ───────────────────────────────────────────

    @staticmethod
    def _get_monday(d: date) -> date:
        """Get the Monday of the week containing the given date"""
        return d - timedelta(days=d.weekday())

    @staticmethod
    def _expand_dates(week_monday: date, interval_days: int) -> List[date]:
        """
        Expand a template into specific dates for the week based on interval_days.
        
        interval_days=1 -> [Mon, Tue, Wed, Thu, Fri, Sat, Sun]
        interval_days=7 -> [Any single day] (Handled by shuffle_tasks now)
        Others -> Fixed pattern starting Mon
        """
        dates = []
        current = week_monday
        week_end = week_monday + timedelta(days=6)  # Sunday
        
        # Standard rigid expansion
        while current <= week_end:
            dates.append(current)
            current += timedelta(days=interval_days)
        return dates

    @staticmethod
    def _resolve_week_monday(week_of: Optional[date]) -> date:
        """Pick the target week's Monday. Sundays bump to next week."""
        if week_of is None:
            today = date.today()
            if today.weekday() == 6:  # Sunday → next week
                return today + timedelta(days=1)
            return TaskAssignmentService._get_monday(today)
        return TaskAssignmentService._get_monday(week_of)

    @staticmethod
    async def _load_shuffle_inputs(
        db: AsyncSession, family_id: UUID
    ) -> tuple[list[TaskTemplate], list[TaskTemplate], list[User]]:
        """Fetch regular templates, bonus templates, and active members."""
        regular_query = select(TaskTemplate).where(
            and_(
                TaskTemplate.family_id == family_id,
                TaskTemplate.is_active == True,
                TaskTemplate.is_bonus == False,
            )
        )
        regular_templates = list((await db.execute(regular_query)).scalars().all())

        bonus_query = select(TaskTemplate).where(
            and_(
                TaskTemplate.family_id == family_id,
                TaskTemplate.is_active == True,
                TaskTemplate.is_bonus == True,
            )
        )
        bonus_templates = list((await db.execute(bonus_query)).scalars().all())

        members_query = select(User).where(
            and_(
                User.family_id == family_id,
                User.is_active == True,
            )
        )
        members = list((await db.execute(members_query)).scalars().all())

        return regular_templates, bonus_templates, members

    @staticmethod
    async def _compute_member_carry(
        db: AsyncSession,
        family_id: UUID,
        week_monday: date,
        member_ids: list[UUID],
        lookback_weeks: int = 2,
    ) -> dict[UUID, int]:
        """
        Cross-week fairness: sum of template points assigned to each member in the
        prior `lookback_weeks`. Members with high carry are picked LAST.
        Excludes CANCELLED rows.
        """
        if lookback_weeks <= 0 or not member_ids:
            return {mid: 0 for mid in member_ids}

        start = week_monday - timedelta(weeks=lookback_weeks)
        query = (
            select(
                TaskAssignment.assigned_to,
                func.coalesce(func.sum(TaskTemplate.points), 0).label("pts"),
            )
            .join(TaskTemplate, TaskAssignment.template_id == TaskTemplate.id)
            .where(
                and_(
                    TaskAssignment.family_id == family_id,
                    TaskAssignment.week_of >= start,
                    TaskAssignment.week_of < week_monday,
                    TaskAssignment.status != AssignmentStatus.CANCELLED,
                )
            )
            .group_by(TaskAssignment.assigned_to)
        )
        rows = (await db.execute(query)).all()
        carry = {mid: 0 for mid in member_ids}
        for user_id, pts in rows:
            if user_id in carry:
                carry[user_id] = int(pts or 0)
        return carry

    @staticmethod
    def _compute_assignments(
        rng: random.Random,
        family_id: UUID,
        week_monday: date,
        regular_templates: list[TaskTemplate],
        bonus_templates: list[TaskTemplate],
        members: list[User],
        member_carry: Optional[dict[UUID, int]] = None,
    ) -> tuple[list[TaskAssignment], dict[UUID, int]]:
        """
        Pure builder — produces TaskAssignment instances WITHOUT db.add/commit.
        Caller decides whether to persist.

        Returns (assignments, totals_per_member) where totals exclude carry.
        """
        if not members:
            raise ValidationException("No active family members found")

        members = list(members)
        rng.shuffle(members)  # Tie-break ordering for ties — deterministic via seeded rng

        week_dates = [week_monday + timedelta(days=i) for i in range(7)]
        date_strs = [d.isoformat() for d in week_dates]

        member_load = {m.id: {d_str: 0 for d_str in date_strs} for m in members}
        carry = member_carry or {m.id: 0 for m in members}
        # Member total (current week) — used for cross-day fairness comparisons
        member_total = {m.id: 0 for m in members}
        totals: dict[UUID, int] = {m.id: 0 for m in members}

        regular_templates = sorted(regular_templates, key=lambda t: t.points, reverse=True)
        rotation_state: dict[UUID, int] = {}
        assignments: list[TaskAssignment] = []

        def _new_assignment(template_id: UUID, user_id: UUID, d: date) -> TaskAssignment:
            return TaskAssignment(
                template_id=template_id,
                assigned_to=user_id,
                family_id=family_id,
                status=AssignmentStatus.PENDING,
                assigned_date=d,
                week_of=week_monday,
            )

        def _credit(user_id: UUID, d: date, points: int) -> None:
            member_load[user_id][d.isoformat()] += points
            member_total[user_id] += points
            totals[user_id] += points

        def _bias(user_id: UUID) -> int:
            return member_total[user_id] + carry.get(user_id, 0)

        for template in regular_templates:
            eligible_members = members

            allowed = template.allowed_roles or None
            if allowed:
                allowed_lower = {r.lower() for r in allowed}
                eligible_members = [
                    m for m in eligible_members
                    if (m.role.value if hasattr(m.role, "value") else str(m.role)).lower()
                    in allowed_lower
                ]
                if not eligible_members:
                    continue

            if template.assignment_type == AssignmentType.FIXED:
                if not template.assigned_user_ids:
                    continue
                eligible_members = [m for m in members if str(m.id) in template.assigned_user_ids]
                if not eligible_members:
                    continue
            elif template.assignment_type == AssignmentType.ROTATE:
                if not template.assigned_user_ids:
                    continue
                eligible_members = [m for m in members if str(m.id) in template.assigned_user_ids]
                if not eligible_members:
                    continue
                rotation_state.setdefault(template.id, 0)

            if template.interval_days == 7:
                task_dates = week_dates
            else:
                task_dates = TaskAssignmentService._expand_dates(
                    week_monday, template.interval_days
                )

            if template.assignment_type == AssignmentType.FIXED:
                fixed_user = eligible_members[0]
                for d in task_dates:
                    assignments.append(_new_assignment(template.id, fixed_user.id, d))
                    _credit(fixed_user.id, d, template.points)

            elif template.assignment_type == AssignmentType.ROTATE:
                for d in task_dates:
                    idx = rotation_state[template.id]
                    chosen = eligible_members[idx % len(eligible_members)]
                    assignments.append(_new_assignment(template.id, chosen.id, d))
                    _credit(chosen.id, d, template.points)
                    rotation_state[template.id] += 1

            else:  # AUTO
                if template.interval_days == 7:
                    # Pick (member, day) slot with min (day-load + cross-week bias)
                    candidates = [
                        (member_load[m.id][d.isoformat()] + _bias(m.id), m, d)
                        for m in eligible_members
                        for d in week_dates
                    ]
                    rng.shuffle(candidates)
                    _, best_member, best_date = min(candidates, key=lambda x: x[0])
                    assignments.append(
                        _new_assignment(template.id, best_member.id, best_date)
                    )
                    _credit(best_member.id, best_date, template.points)

                elif template.interval_days == 1:
                    for d in week_dates:
                        d_str = d.isoformat()
                        day_candidates = [
                            (member_load[m.id][d_str] + _bias(m.id), m)
                            for m in eligible_members
                        ]
                        rng.shuffle(day_candidates)
                        _, best_member = min(day_candidates, key=lambda x: x[0])
                        assignments.append(
                            _new_assignment(template.id, best_member.id, d)
                        )
                        _credit(best_member.id, d, template.points)

                else:
                    dates = task_dates
                    candidates = []
                    for m in eligible_members:
                        max_impact = 0
                        cum = 0
                        for d in dates:
                            load = member_load[m.id][d.isoformat()]
                            if load > max_impact:
                                max_impact = load
                            cum += load
                        candidates.append(
                            (cum + _bias(m.id), max_impact, m)
                        )
                    rng.shuffle(candidates)
                    _, _, best_member = min(candidates, key=lambda x: (x[0], x[1]))
                    for d in dates:
                        assignments.append(
                            _new_assignment(template.id, best_member.id, d)
                        )
                        _credit(best_member.id, d, template.points)

        for template in bonus_templates:
            dates = TaskAssignmentService._expand_dates(
                week_monday, template.interval_days
            )

            # Filter eligible members by allowed_roles + assigned_user_ids.
            eligible = list(members)
            allowed = template.allowed_roles or None
            if allowed:
                allowed_lower = {r.lower() for r in allowed}
                eligible = [
                    m for m in eligible
                    if (m.role.value if hasattr(m.role, "value") else str(m.role)).lower()
                    in allowed_lower
                ]
            if template.assigned_user_ids:
                target_ids = set(template.assigned_user_ids)
                eligible = [m for m in eligible if str(m.id) in target_ids]
            if not eligible:
                continue

            mode = getattr(template, "gig_mode", "claim") or "claim"

            if mode == "rotation":
                # One assignment per date, member cycled by week index so
                # week 1 → member 0, week 2 → member 1, etc.
                week_idx = week_monday.toordinal() // 7
                for i, d in enumerate(dates):
                    chosen = eligible[(week_idx + i) % len(eligible)]
                    assignments.append(_new_assignment(template.id, chosen.id, d))
            else:
                # claim / competition / collaboration: every eligible
                # member gets a row per date so they all see the gig.
                for d in dates:
                    for member in eligible:
                        assignments.append(_new_assignment(template.id, member.id, d))

        return assignments, totals

    @staticmethod
    async def shuffle_tasks(
        db: AsyncSession,
        family_id: UUID,
        week_of: Optional[date] = None,
    ) -> List[TaskAssignment]:
        """
        Generate weekly task assignments by shuffling templates across family members.

        Deterministic per (family_id, week_monday): same input → same output.
        Idempotent for PENDING (re-shuffle replaces only PENDING rows).
        """
        week_monday = TaskAssignmentService._resolve_week_monday(week_of)

        regular_templates, bonus_templates, members = (
            await TaskAssignmentService._load_shuffle_inputs(db, family_id)
        )

        carry = await TaskAssignmentService._compute_member_carry(
            db, family_id, week_monday, [m.id for m in members]
        )

        rng = random.Random(f"{family_id}:{week_monday.isoformat()}")

        # Delete existing PENDING rows for this week (preserves completed/overdue/cancelled)
        delete_stmt = sql_delete(TaskAssignment).where(
            and_(
                TaskAssignment.family_id == family_id,
                TaskAssignment.week_of == week_monday,
                TaskAssignment.status == AssignmentStatus.PENDING,
            )
        )
        await db.execute(delete_stmt)

        assignments, _ = TaskAssignmentService._compute_assignments(
            rng,
            family_id,
            week_monday,
            regular_templates,
            bonus_templates,
            members,
            member_carry=carry,
        )

        for a in assignments:
            db.add(a)

        await db.commit()
        for a in assignments:
            await db.refresh(a)

        return assignments

    @staticmethod
    async def preview_shuffle(
        db: AsyncSession,
        family_id: UUID,
        week_of: Optional[date] = None,
    ) -> dict:
        """
        Dry-run shuffle — no DB writes. Returns the proposed assignment plan plus
        per-member point totals (current week) and cross-week carry used for bias.
        """
        week_monday = TaskAssignmentService._resolve_week_monday(week_of)

        regular_templates, bonus_templates, members = (
            await TaskAssignmentService._load_shuffle_inputs(db, family_id)
        )
        carry = await TaskAssignmentService._compute_member_carry(
            db, family_id, week_monday, [m.id for m in members]
        )

        rng = random.Random(f"{family_id}:{week_monday.isoformat()}")
        assignments, totals = TaskAssignmentService._compute_assignments(
            rng,
            family_id,
            week_monday,
            regular_templates,
            bonus_templates,
            members,
            member_carry=carry,
        )

        # Build lightweight detail dicts (no DB IDs since not persisted)
        member_by_id = {m.id: m for m in members}
        template_by_id = {t.id: t for t in (regular_templates + bonus_templates)}
        items = []
        for a in assignments:
            tmpl = template_by_id.get(a.template_id)
            mem = member_by_id.get(a.assigned_to)
            items.append({
                "template_id": a.template_id,
                "template_title": tmpl.title if tmpl else "",
                "template_title_es": tmpl.title_es if tmpl else None,
                "template_points": tmpl.points if tmpl else 0,
                "template_is_bonus": tmpl.is_bonus if tmpl else False,
                "assigned_to": a.assigned_to,
                "assigned_user_name": mem.name if mem else "",
                "assigned_date": a.assigned_date,
                "week_of": a.week_of,
            })

        return {
            "week_of": week_monday,
            "totals_by_member": [
                {
                    "user_id": m.id,
                    "user_name": m.name,
                    "points_this_week": totals.get(m.id, 0),
                    "points_carry": carry.get(m.id, 0),
                }
                for m in members
            ],
            "assignments": items,
        }

    # ─── Assignment Queries ──────────────────────────────────────────

    @staticmethod
    async def get_assignment(
        db: AsyncSession, assignment_id: UUID, family_id: UUID
    ) -> TaskAssignment:
        """Get an assignment by ID with template eagerly loaded"""
        query = (
            select(TaskAssignment)
            .options(
                selectinload(TaskAssignment.template),
                selectinload(TaskAssignment.assigned_user),
            )
            .where(
                and_(
                    TaskAssignment.id == assignment_id,
                    TaskAssignment.family_id == family_id,
                )
            )
        )
        result = await db.execute(query)
        assignment = result.scalar_one_or_none()
        if not assignment:
            raise NotFoundException("Assignment not found")
        return assignment

    @staticmethod
    async def list_assignments_for_week(
        db: AsyncSession,
        family_id: UUID,
        week_of: date,
        user_id: Optional[UUID] = None,
        status: Optional[AssignmentStatus] = None,
    ) -> List[TaskAssignment]:
        """List assignments for a given week"""
        week_monday = TaskAssignmentService._get_monday(week_of)

        query = (
            select(TaskAssignment)
            .options(
                selectinload(TaskAssignment.template),
                selectinload(TaskAssignment.assigned_user),
            )
            .where(
                and_(
                    TaskAssignment.family_id == family_id,
                    TaskAssignment.week_of == week_monday,
                )
            )
        )

        if user_id:
            query = query.where(TaskAssignment.assigned_to == user_id)
        if status:
            query = query.where(TaskAssignment.status == status)

        query = query.order_by(
            TaskAssignment.assigned_date.asc(), TaskAssignment.created_at.asc()
        )
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def list_assignments_for_date(
        db: AsyncSession,
        family_id: UUID,
        target_date: date,
        user_id: Optional[UUID] = None,
    ) -> List[TaskAssignment]:
        """List assignments for a specific date"""
        query = (
            select(TaskAssignment)
            .options(
                selectinload(TaskAssignment.template),
                selectinload(TaskAssignment.assigned_user),
            )
            .where(
                and_(
                    TaskAssignment.family_id == family_id,
                    TaskAssignment.assigned_date == target_date,
                )
            )
        )

        if user_id:
            query = query.where(TaskAssignment.assigned_to == user_id)

        query = query.order_by(TaskAssignment.created_at.asc())
        result = await db.execute(query)
        return list(result.scalars().all())

    # ─── Completion + Gating ─────────────────────────────────────────

    @staticmethod
    async def has_open_mandatory_through(
        db: AsyncSession,
        user_id: UUID,
        family_id: UUID,
        through_date: date,
    ) -> bool:
        """
        True if any mandatory (non-bonus) assignment with assigned_date
        on or before ``through_date`` is still open (PENDING or OVERDUE).

        Carry-over semantics: an unfinished mandatory from yesterday
        blocks today's gigs. CANCELLED counts as resolved (parent waived).
        Future-dated mandatory rows are intentionally ignored.
        """
        q = (
            select(func.count())
            .select_from(TaskAssignment)
            .join(TaskTemplate, TaskAssignment.template_id == TaskTemplate.id)
            .where(
                and_(
                    TaskAssignment.assigned_to == user_id,
                    TaskAssignment.family_id == family_id,
                    TaskAssignment.assigned_date <= through_date,
                    TaskTemplate.is_bonus.is_(False),
                    TaskAssignment.status.in_(
                        [AssignmentStatus.PENDING, AssignmentStatus.OVERDUE]
                    ),
                )
            )
        )
        return (await db.execute(q)).scalar_one() > 0

    @staticmethod
    async def complete_assignment(
        db: AsyncSession,
        assignment_id: UUID,
        family_id: UUID,
        user_id: UUID,
        proof_text: Optional[str] = None,
        proof_image_url: Optional[str] = None,
    ) -> TaskAssignment:
        """
        Mark an assignment as completed.

        Mandatory (is_bonus=false): completes silently, awards no points.
        Gig (is_bonus=true): requires all today's mandatory done first, requires
        proof_text, and enters PENDING approval state. Points are credited only
        when a parent approves via approve_gig().
        """
        assignment = await TaskAssignmentService.get_assignment(
            db, assignment_id, family_id
        )

        if not assignment.can_complete:
            raise ValidationException(
                f"Assignment cannot be completed. Current status: {assignment.status.value}"
            )

        if assignment.assigned_to != user_id:
            raise ForbiddenException(
                "Only the assigned user can complete this assignment"
            )

        template = assignment.template
        auto_approved = False

        if template.is_bonus:
            # Gig path
            has_open_mandatory = await TaskAssignmentService.has_open_mandatory_through(
                db, user_id, family_id, assignment.assigned_date
            )
            if has_open_mandatory:
                raise ForbiddenException(
                    "Finish any open mandatory tasks (today + overdue) before claiming a gig"
                )

            if not proof_text or not proof_text.strip():
                raise ValidationException("Gigs require proof text describing what you did")

            assignment.status = AssignmentStatus.COMPLETED
            assignment.completed_at = datetime.now(timezone.utc)
            assignment.proof_text = proof_text.strip()
            if proof_image_url:
                assignment.proof_image_url = proof_image_url

            # Auto-approval has two independent paths:
            #   1. Trust streak — user has earned N consecutive approvals.
            #   2. AI photo validation — vision model agrees the photo
            #      shows the task done, above settings threshold.
            # If either path approves, points credit immediately.
            from app.core.config import settings
            from app.services.points_service import PointsService
            from app.services.task_proof_validator import validate_proof_photo
            child = await get_user_by_id(db, user_id)
            threshold = max(1, settings.GIG_AUTO_APPROVE_STREAK)

            auto_approved = False
            approval_reason = ""

            if child.gig_trust_streak >= threshold:
                auto_approved = True
                approval_reason = "Auto-approved via trust streak"
            elif assignment.proof_image_url:
                validation = await validate_proof_photo(
                    assignment.proof_image_url,
                    template.title,
                    template.description,
                )
                if validation is not None:
                    assignment.ai_validation_score = validation.score
                    assignment.ai_validation_notes = validation.explanation
                    if validation.score >= settings.GIG_AI_AUTO_APPROVE_THRESHOLD:
                        auto_approved = True
                        approval_reason = (
                            f"Auto-approved via AI photo check "
                            f"(score {validation.score:.2f}): {validation.explanation}"
                        )

            if auto_approved:
                assignment.approval_status = ApprovalStatus.APPROVED
                assignment.approved_at = datetime.now(timezone.utc)
                assignment.approval_notes = approval_reason
                await PointsService.award_gig_points(
                    db, user_id, assignment.id, template.award_points_per_completer
                )
                child.gig_trust_streak += 1
                from app.services.notification_service import NotificationService
                from app.services.pet_service import PetService
                from app.models.notification import NotificationType as NT
                await NotificationService.create_no_commit(
                    db,
                    family_id=family_id,
                    user_id=user_id,
                    type=NT.GIG_APPROVED,
                    title=f"✅ +{template.award_points_per_completer} pts",
                    body=f"'{template.title}' approved automatically. {approval_reason}",
                )
                await PetService.on_task_completed(db, user_id, is_bonus=True)
            else:
                assignment.approval_status = ApprovalStatus.PENDING
        else:
            # Mandatory path — silent, no points, no approval
            assignment.status = AssignmentStatus.COMPLETED
            assignment.completed_at = datetime.now(timezone.utc)
            # approval_status stays NONE; no PointTransaction row
            from app.services.pet_service import PetService
            await PetService.on_task_completed(db, user_id, is_bonus=False)

        await db.commit()
        await db.refresh(assignment)

        if auto_approved:
            try:
                from app.services.onboarding_service import OnboardingService
                await OnboardingService.advance(family_id, "points_awarded", db)
                await db.commit()
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    "onboarding advance points_awarded failed", exc_info=True
                )
            try:
                from app.services.reward_goal_service import RewardGoalService
                refreshed = await get_user_by_id(db, user_id)
                await RewardGoalService.check_nudge(
                    user_id=user_id,
                    family_id=family_id,
                    new_balance=refreshed.points,
                    db=db,
                )
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    "check_nudge after task auto-approve failed", exc_info=True
                )

        # Fire-and-forget notifications on gig submission. Failures are
        # swallowed so the API response is never blocked by an upstream
        # issue. Skip for auto-approved gigs — parents don't need a
        # heads-up on something already credited.
        if template.is_bonus and assignment.approval_status == ApprovalStatus.PENDING:
            child = await get_user_by_id(db, user_id)
            try:
                from app.services.email_service import EmailService
                await EmailService.notify_parents_gig_pending(
                    db,
                    family_id=family_id,
                    child_name=child.name,
                    gig_title=template.title,
                    proof_text=assignment.proof_text or "",
                    proof_image_url=assignment.proof_image_url,
                )
            except Exception:
                import logging
                logging.getLogger(__name__).exception("notify_parents_gig_pending failed")
            try:
                from app.services.notification_service import NotificationService
                from app.models.notification import NotificationType as NT
                # Family-wide notification (parents see it on dashboard)
                await NotificationService.create(
                    db,
                    family_id=family_id,
                    user_id=None,
                    type=NT.GIG_PENDING_REVIEW,
                    title="🛎️ Gig pending review",
                    body=f"{child.name} finished '{template.title}'. Approve or reject in /parent/approvals.",
                    link="/parent/approvals",
                )
            except Exception:
                import logging
                logging.getLogger(__name__).exception("notification create failed")
            try:
                from app.services.push_service import PushService
                await PushService.fan_out_pending_gig(
                    db,
                    family_id=family_id,
                    child_name=child.name,
                    gig_title=template.title,
                    points=template.award_points_per_completer,
                )
            except Exception:
                import logging
                logging.getLogger(__name__).exception("fan_out_pending_gig push failed")

        return assignment

    # ─── Gig claim (reserve before doing) ────────────────────────────

    @staticmethod
    async def claim_gig(
        db: AsyncSession,
        assignment_id: UUID,
        family_id: UUID,
        user_id: UUID,
    ) -> TaskAssignment:
        """
        Reserve a gig before working on it. Transitions PENDING → CLAIMED.

        Only the assignee can claim. Mandatory rows reject (no claim
        semantic). Gating still applies — must finish open mandatory
        first.
        """
        assignment = await TaskAssignmentService.get_assignment(
            db, assignment_id, family_id
        )

        if not assignment.template.is_bonus:
            raise ValidationException("Only gigs can be claimed")

        if assignment.assigned_to != user_id:
            raise ForbiddenException("Only the assigned user can claim this gig")

        if not assignment.can_claim:
            raise ValidationException(
                f"Gig cannot be claimed in status {assignment.status.value}"
            )

        if await TaskAssignmentService.has_open_mandatory_through(
            db, user_id, family_id, assignment.assigned_date
        ):
            raise ForbiddenException(
                "Finish any open mandatory tasks (today + overdue) before claiming a gig"
            )

        assignment.status = AssignmentStatus.CLAIMED
        assignment.claimed_at = datetime.now(timezone.utc)

        # Competition mode: first claim wins, cancel sibling assignments for
        # the same template+week so other kids see the gig disappear.
        tmpl = assignment.template
        if tmpl and tmpl.is_bonus and tmpl.gig_mode == "competition":
            from sqlalchemy import update as sql_update
            stmt = (
                sql_update(TaskAssignment)
                .where(
                    and_(
                        TaskAssignment.family_id == family_id,
                        TaskAssignment.template_id == tmpl.id,
                        TaskAssignment.week_of == assignment.week_of,
                        TaskAssignment.id != assignment.id,
                        TaskAssignment.status == AssignmentStatus.PENDING,
                    )
                )
                .values(status=AssignmentStatus.CANCELLED)
            )
            await db.execute(stmt)

        await db.commit()
        await db.refresh(assignment)
        return assignment

    @staticmethod
    async def unclaim_gig(
        db: AsyncSession,
        assignment_id: UUID,
        family_id: UUID,
        user_id: UUID,
    ) -> TaskAssignment:
        """Release a claim and return the gig to PENDING."""
        assignment = await TaskAssignmentService.get_assignment(
            db, assignment_id, family_id
        )
        if assignment.assigned_to != user_id:
            raise ForbiddenException("Only the assignee can release a claim")
        if assignment.status != AssignmentStatus.CLAIMED:
            raise ValidationException(
                f"Only CLAIMED gigs can be unclaimed (current: {assignment.status.value})"
            )
        assignment.status = AssignmentStatus.PENDING
        assignment.claimed_at = None
        await db.commit()
        await db.refresh(assignment)
        return assignment

    # ─── Gig approval (parent-only) ──────────────────────────────────

    @staticmethod
    async def approve_gig(
        db: AsyncSession,
        assignment_id: UUID,
        family_id: UUID,
        parent_id: UUID,
        approve: bool,
        notes: Optional[str] = None,
    ) -> TaskAssignment:
        from app.models.user import UserRole
        from app.services.points_service import PointsService
        from app.core.premium import get_family_plan
        from app.services.usage_service import UsageService

        parent = await get_user_by_id(db, parent_id)
        if parent.family_id != family_id or parent.role != UserRole.PARENT:
            raise ForbiddenException("Only parents in this family can approve gigs")

        assignment = await TaskAssignmentService.get_assignment(db, assignment_id, family_id)

        if assignment.approval_status != ApprovalStatus.PENDING:
            raise ValidationException(
                f"Gig already decided (status: {assignment.approval_status.value})"
            )

        assignment.approved_by = parent_id
        assignment.approved_at = datetime.now(timezone.utc)
        assignment.approval_notes = notes

        if approve:
            # Enforce per-family monthly gig approval cap. Atomic increment
            # prevents two concurrent approvals from slipping past the limit.
            plan = await get_family_plan(db, parent)
            limit = int(plan.limits.get("max_gigs_per_month", 3))
            new_count = await UsageService.try_increment_within_limit(
                db, family_id, "gig_completion", limit, amount=1,
            )
            if new_count is None:
                raise ValidationException(
                    f"Family has hit the monthly gig approval cap ({limit}). "
                    "Upgrade to raise the cap."
                )
            assignment.approval_status = ApprovalStatus.APPROVED
            await PointsService.award_gig_points(
                db,
                assignment.assigned_to,
                assignment.id,
                assignment.template.award_points_per_completer,
            )
            # Increment trust streak so the child graduates to
            # auto-approval after enough consecutive approvals.
            child = await get_user_by_id(db, assignment.assigned_to)
            child.gig_trust_streak += 1
            from app.services.notification_service import NotificationService
            from app.services.pet_service import PetService
            from app.models.notification import NotificationType as NT
            await PetService.on_task_completed(
                db, assignment.assigned_to, is_bonus=True
            )
            await db.commit()
            try:
                from app.services.onboarding_service import OnboardingService
                await OnboardingService.advance(family_id, "points_awarded", db)
                await db.commit()
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    "onboarding advance points_awarded failed", exc_info=True
                )
            # NotificationService.create commits + fans out push.
            await NotificationService.create(
                db,
                family_id=family_id,
                user_id=assignment.assigned_to,
                type=NT.GIG_APPROVED,
                title=f"✅ +{assignment.template.award_points_per_completer} pts",
                body=f"'{assignment.template.title}' approved by parent.",
                link="/dashboard",
            )
        else:
            assignment.approval_status = ApprovalStatus.REJECTED
            # Reset trust streak — a rejection signals the child still
            # needs review on subsequent gigs.
            child = await get_user_by_id(db, assignment.assigned_to)
            child.gig_trust_streak = 0
            from app.services.notification_service import NotificationService
            from app.models.notification import NotificationType as NT
            await db.commit()
            await NotificationService.create(
                db,
                family_id=family_id,
                user_id=assignment.assigned_to,
                type=NT.GIG_REJECTED,
                title="❌ Gig rejected",
                body=f"'{assignment.template.title}' was not approved. {notes or ''}".strip(),
                link="/dashboard",
            )

        await db.commit()
        await db.refresh(assignment)
        return assignment

    @staticmethod
    async def list_for_user_today_with_locks(
        db: AsyncSession,
        user_id: UUID,
        family_id: UUID,
    ) -> list[dict]:
        """Return today's assignments for a user with is_locked + approval fields."""
        today = await TaskAssignmentService._user_local_today(db, user_id)
        has_open = await TaskAssignmentService.has_open_mandatory_through(
            db, user_id, family_id, today
        )
        q = (
            select(TaskAssignment)
            .options(selectinload(TaskAssignment.template))
            .where(
                TaskAssignment.assigned_to == user_id,
                TaskAssignment.family_id == family_id,
                TaskAssignment.assigned_date == today,
            )
            .order_by(TaskAssignment.assigned_date)
        )
        rows = (await db.execute(q)).scalars().all()
        out = []
        for r in rows:
            is_bonus = r.template.is_bonus
            out.append({
                "id": r.id,
                "template_id": r.template_id,
                "title": r.template.title,
                "points": r.template.points,
                "is_bonus": is_bonus,
                "status": r.status.value,
                "approval_status": r.approval_status.value if r.approval_status else "none",
                "proof_text": r.proof_text,
                "is_locked": is_bonus and has_open and r.status != AssignmentStatus.COMPLETED,
                "assigned_date": r.assigned_date,
                "completed_at": r.completed_at,
            })
        return out

    @staticmethod
    async def list_pending_approvals(
        db: AsyncSession,
        family_id: UUID,
    ) -> list[TaskAssignment]:
        from sqlalchemy.orm import selectinload
        q = (
            select(TaskAssignment)
            .options(selectinload(TaskAssignment.template))
            .where(
                TaskAssignment.family_id == family_id,
                TaskAssignment.approval_status == ApprovalStatus.PENDING,
            )
            .order_by(TaskAssignment.completed_at.asc())
        )
        result = await db.execute(q)
        return list(result.scalars().all())

    # ─── Parent Edit (reassign / reschedule / cancel) ────────────────

    @staticmethod
    async def patch_assignment(
        db: AsyncSession,
        assignment_id: UUID,
        family_id: UUID,
        assigned_to: Optional[UUID] = None,
        assigned_date: Optional[date] = None,
        status: Optional[AssignmentStatus] = None,
    ) -> TaskAssignment:
        """
        Parent-only edit on an individual assignment.

        - assigned_to: must belong to same family.
        - assigned_date: any date; week_of recomputed to its Monday.
        - status: only PENDING (revive) or CANCELLED allowed. COMPLETED must go
          through complete_assignment() so points are awarded correctly.
        """
        assignment = await TaskAssignmentService.get_assignment(
            db, assignment_id, family_id
        )

        if status is not None and status not in (
            AssignmentStatus.PENDING,
            AssignmentStatus.CANCELLED,
        ):
            raise ValidationException(
                "PATCH only allows status=pending or status=cancelled. Use /complete to mark completed."
            )

        if assigned_to is not None:
            new_user = await get_user_by_id(db, assigned_to)
            if new_user.family_id != family_id:
                raise ForbiddenException(
                    "Cannot assign to a user outside this family"
                )
            assignment.assigned_to = assigned_to

        if assigned_date is not None:
            assignment.assigned_date = assigned_date
            assignment.week_of = TaskAssignmentService._get_monday(assigned_date)

        if status is not None:
            assignment.status = status
            if status == AssignmentStatus.PENDING:
                assignment.completed_at = None

        await db.commit()
        # Re-fetch with template + user eagerly loaded
        return await TaskAssignmentService.get_assignment(
            db, assignment_id, family_id
        )

    # ─── Daily Progress ──────────────────────────────────────────────

    @staticmethod
    async def get_daily_progress(
        db: AsyncSession,
        user_id: UUID,
        family_id: UUID,
        target_date: Optional[date] = None,
    ) -> dict:
        """
        Get daily progress summary for a user.
        Returns required/bonus counts and whether bonus is unlocked.
        "today" is computed in the user's family timezone when target_date is None.
        """
        check_date = target_date or await TaskAssignmentService._user_local_today(db, user_id)

        assignments = await TaskAssignmentService.list_assignments_for_date(
            db, family_id, check_date, user_id
        )

        required_assignments = [a for a in assignments if not a.template.is_bonus]
        bonus_assignments = [a for a in assignments if a.template.is_bonus]

        required_completed = sum(
            1 for a in required_assignments if a.status == AssignmentStatus.COMPLETED
        )
        bonus_completed = sum(
            1 for a in bonus_assignments if a.status == AssignmentStatus.COMPLETED
        )

        # Carry-over: also block bonus when any prior-day mandatory is
        # still PENDING/OVERDUE. has_open_mandatory_through covers both
        # same-day and historical opens.
        has_open_mandatory = await TaskAssignmentService.has_open_mandatory_through(
            db, user_id, family_id, check_date
        )
        bonus_unlocked = not has_open_mandatory

        return {
            "date": check_date,
            "required_total": len(required_assignments),
            "required_completed": required_completed,
            "bonus_unlocked": bonus_unlocked,
            "bonus_total": len(bonus_assignments),
            "bonus_completed": bonus_completed,
            "assignments": assignments,
        }

    # ─── Overdue Check ───────────────────────────────────────────────

    @staticmethod
    async def _family_local_today(db: AsyncSession, family_id: UUID) -> date:
        """Today's date in the family's timezone (fallback UTC)."""
        from zoneinfo import ZoneInfo
        from app.models.family import Family
        family = await db.get(Family, family_id)
        tz_name = (family.timezone if family and family.timezone else None) or "UTC"
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = ZoneInfo("UTC")
        return datetime.now(tz).date()

    @staticmethod
    async def check_overdue_assignments(
        db: AsyncSession, family_id: UUID
    ) -> List[TaskAssignment]:
        """Check for overdue assignments and update their status (family-tz aware)."""
        today = await TaskAssignmentService._family_local_today(db, family_id)

        query = select(TaskAssignment).where(
            and_(
                TaskAssignment.family_id == family_id,
                TaskAssignment.status == AssignmentStatus.PENDING,
                TaskAssignment.assigned_date < today,
            )
        )

        assignments = list((await db.execute(query)).scalars().all())

        for assignment in assignments:
            assignment.status = AssignmentStatus.OVERDUE

        if assignments:
            await db.commit()

        return assignments

    @staticmethod
    async def mark_overdue_all(db: AsyncSession) -> int:
        """
        Sweep across ALL families: flip PENDING rows with assigned_date < today
        to OVERDUE, where "today" is each family's local date. Intended for the
        background scheduler.

        When a flipped assignment's template has ``auto_late_penalty`` set, a
        Consequence row is instantiated for the assigned user (idempotent
        because status only transitions PENDING → OVERDUE once).
        """
        from app.models.family import Family
        from app.models.consequence import (
            Consequence,
            ConsequenceSeverity,
            RestrictionType,
        )

        family_rows = (await db.execute(select(Family.id))).scalars().all()
        now_utc = datetime.now(timezone.utc)
        total = 0
        for family_id in family_rows:
            today = await TaskAssignmentService._family_local_today(db, family_id)
            stale_q = (
                select(TaskAssignment)
                .options(selectinload(TaskAssignment.template))
                .where(
                    and_(
                        TaskAssignment.family_id == family_id,
                        TaskAssignment.status == AssignmentStatus.PENDING,
                        TaskAssignment.assigned_date < today,
                    )
                )
            )
            stale = list((await db.execute(stale_q)).scalars().all())
            for a in stale:
                a.status = AssignmentStatus.OVERDUE
                a.updated_at = now_utc
                tmpl = a.template
                if tmpl is None or not tmpl.auto_late_penalty:
                    continue
                if not tmpl.late_restriction_type:
                    continue
                try:
                    restriction = RestrictionType(tmpl.late_restriction_type)
                except ValueError:
                    continue
                severity_raw = tmpl.late_severity or "low"
                try:
                    severity = ConsequenceSeverity(severity_raw)
                except ValueError:
                    severity = ConsequenceSeverity.LOW
                duration = max(1, min(30, int(tmpl.late_duration_days or 1)))
                end_dt = now_utc + timedelta(days=duration)
                title = f"Late: {tmpl.title}"[:200]
                penalty = Consequence(
                    title=title,
                    description=(
                        f"Auto-applied because task '{tmpl.title}' "
                        f"({a.assigned_date.isoformat()}) was not completed on time."
                    ),
                    severity=severity,
                    restriction_type=restriction,
                    duration_days=duration,
                    active=True,
                    resolved=False,
                    triggered_by_assignment_id=a.id,
                    applied_to_user=a.assigned_to,
                    family_id=family_id,
                    start_date=now_utc,
                    end_date=end_dt,
                )
                db.add(penalty)
                from app.services.notification_service import NotificationService
                from app.models.notification import NotificationType as NT
                await NotificationService.create_no_commit(
                    db,
                    family_id=family_id,
                    user_id=a.assigned_to,
                    type=NT.LATE_PENALTY_APPLIED,
                    title=f"⏰ Late: {tmpl.title}",
                    body=(
                        f"Auto-penalty applied: {restriction.value} "
                        f"for {duration} day(s)."
                    ),
                )
            total += len(stale)
        await db.commit()
        return total
