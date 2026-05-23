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
            for d in dates:
                for member in members:
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
    async def check_all_required_done_today(
        db: AsyncSession,
        user_id: UUID,
        family_id: UUID,
        target_date: Optional[date] = None,
    ) -> bool:
        """
        Check if a user has completed all non-bonus assignments for today.
        This is the gating check for bonus task access.
        """
        check_date = target_date or date.today()

        # Count required (non-bonus) assignments for today
        total_query = (
            select(func.count())
            .select_from(TaskAssignment)
            .join(TaskTemplate, TaskAssignment.template_id == TaskTemplate.id)
            .where(
                and_(
                    TaskAssignment.assigned_to == user_id,
                    TaskAssignment.family_id == family_id,
                    TaskAssignment.assigned_date == check_date,
                    TaskTemplate.is_bonus == False,
                )
            )
        )
        total = (await db.execute(total_query)).scalar_one()

        if total == 0:
            # No required tasks today — bonus unlocked
            return True

        # Count completed required assignments for today
        completed_query = (
            select(func.count())
            .select_from(TaskAssignment)
            .join(TaskTemplate, TaskAssignment.template_id == TaskTemplate.id)
            .where(
                and_(
                    TaskAssignment.assigned_to == user_id,
                    TaskAssignment.family_id == family_id,
                    TaskAssignment.assigned_date == check_date,
                    TaskTemplate.is_bonus == False,
                    TaskAssignment.status == AssignmentStatus.COMPLETED,
                )
            )
        )
        completed = (await db.execute(completed_query)).scalar_one()

        return completed >= total

    @staticmethod
    async def complete_assignment(
        db: AsyncSession,
        assignment_id: UUID,
        family_id: UUID,
        user_id: UUID,
        proof_text: Optional[str] = None,
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

        if template.is_bonus:
            # Gig path
            all_required_done = await TaskAssignmentService.check_all_required_done_today(
                db, user_id, family_id, assignment.assigned_date
            )
            if not all_required_done:
                raise ForbiddenException(
                    "Complete today's mandatory tasks before claiming a gig"
                )

            if not proof_text or not proof_text.strip():
                raise ValidationException("Gigs require proof text describing what you did")

            assignment.status = AssignmentStatus.COMPLETED
            assignment.completed_at = datetime.now(timezone.utc)
            assignment.approval_status = ApprovalStatus.PENDING
            assignment.proof_text = proof_text.strip()
        else:
            # Mandatory path — silent, no points, no approval
            assignment.status = AssignmentStatus.COMPLETED
            assignment.completed_at = datetime.now(timezone.utc)
            # approval_status stays NONE; no PointTransaction row

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
            assignment.approval_status = ApprovalStatus.APPROVED
            await PointsService.award_gig_points(
                db, assignment.assigned_to, assignment.id, assignment.template.points
            )
        else:
            assignment.approval_status = ApprovalStatus.REJECTED

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
        all_done = await TaskAssignmentService.check_all_required_done_today(
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
                "is_locked": is_bonus and not all_done and r.status != AssignmentStatus.COMPLETED,
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

        bonus_unlocked = required_completed >= len(required_assignments)

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
        """
        from sqlalchemy import update as sql_update
        from app.models.family import Family

        family_rows = (await db.execute(select(Family.id))).scalars().all()
        now_utc = datetime.now(timezone.utc)
        total = 0
        for family_id in family_rows:
            today = await TaskAssignmentService._family_local_today(db, family_id)
            stmt = (
                sql_update(TaskAssignment)
                .where(
                    and_(
                        TaskAssignment.family_id == family_id,
                        TaskAssignment.status == AssignmentStatus.PENDING,
                        TaskAssignment.assigned_date < today,
                    )
                )
                .values(status=AssignmentStatus.OVERDUE, updated_at=now_utc)
            )
            result = await db.execute(stmt)
            total += result.rowcount or 0
        await db.commit()
        return total
