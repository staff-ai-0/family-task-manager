"""Routine service — icon tap-through routines for pre-readers.

Business rules:

- Parents author routines + steps; kids run them. Every query is scoped by
  ``family_id`` (multi-tenant isolation).
- A routine is either per-kid (``assigned_user_id`` set) or family-wide
  (``assigned_user_id`` NULL — every member runs an independent daily copy).
- A kid completes steps tap-by-tap. When EVERY current step is done for the
  day, the routine awards POINTS (privileges — never cash) exactly once and
  feeds the pet via ``PetService.on_task_completed``. Partial completion awards
  nothing. The one-shot ``RoutineProgress.awarded`` guard makes the reward
  idempotent across re-taps and mid-day edits.
"""

from datetime import date, datetime
from typing import Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import (
    ForbiddenException,
    NotFoundException,
    ValidationException,
)
from app.models.point_transaction import PointTransaction, TransactionType
from app.models.routine import (
    TIME_OF_DAY_VALUES,
    Routine,
    RoutineProgress,
    RoutineStep,
)
from app.models.user import User, UserRole
from app.services.base_service import get_user_by_id


def _norm_icon(value: Optional[str], fallback: str) -> str:
    v = (value or "").strip()
    return v[:16] if v else fallback


class RoutineService:
    # ─── Local day (family timezone) ─────────────────────────────────

    @staticmethod
    async def _user_local_today(db: AsyncSession, user: User) -> date:
        """Today's date in the user's family timezone (matches task logic)."""
        from app.models.family import Family

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

    # ─── Parent authoring (CRUD) ─────────────────────────────────────

    @staticmethod
    async def create_routine(
        db: AsyncSession,
        *,
        family_id: UUID,
        created_by: UUID,
        name: str,
        name_es: Optional[str] = None,
        icon: Optional[str] = None,
        color: Optional[str] = None,
        time_of_day: str = "morning",
        assigned_user_id: Optional[UUID] = None,
        points_reward: int = 10,
        sort_order: int = 0,
        steps: Optional[list[dict]] = None,
    ) -> Routine:
        name = (name or "").strip()
        if not name:
            raise ValidationException("Routine name is required")
        if time_of_day not in TIME_OF_DAY_VALUES:
            raise ValidationException(f"Invalid time_of_day: {time_of_day}")
        if points_reward < 0:
            raise ValidationException("points_reward must be >= 0")
        if assigned_user_id is not None:
            await RoutineService._verify_member(db, family_id, assigned_user_id)

        routine = Routine(
            family_id=family_id,
            created_by=created_by,
            name=name[:120],
            name_es=(name_es or "").strip()[:120] or None,
            icon=_norm_icon(icon, "🌅"),
            color=(color or "").strip()[:9] or None,
            time_of_day=time_of_day,
            assigned_user_id=assigned_user_id,
            points_reward=int(points_reward),
            sort_order=int(sort_order),
        )
        db.add(routine)
        await db.flush()

        for i, step in enumerate(steps or []):
            label = (step.get("label") or "").strip()
            if not label:
                continue
            db.add(
                RoutineStep(
                    routine_id=routine.id,
                    label=label[:120],
                    label_es=(step.get("label_es") or "").strip()[:120] or None,
                    icon=_norm_icon(step.get("icon"), "✅"),
                    sort_order=step.get("sort_order", i),
                )
            )

        await db.commit()
        return await RoutineService.get_routine_or_404(db, family_id, routine.id)

    @staticmethod
    async def list_routines(
        db: AsyncSession,
        family_id: UUID,
        *,
        for_user: Optional[User] = None,
        active_only: bool = False,
    ) -> list[Routine]:
        """Routines in a family, steps eager-loaded, ordered for display.

        ``for_user`` (a kid) narrows to routines they run: assigned to them OR
        family-wide. Parents pass ``for_user=None`` to see everything.
        """
        q = (
            select(Routine)
            .where(Routine.family_id == family_id)
            .options(selectinload(Routine.steps))
            .order_by(Routine.time_of_day, Routine.sort_order, Routine.created_at)
        )
        if active_only:
            q = q.where(Routine.is_active.is_(True))
        if for_user is not None:
            q = q.where(
                (Routine.assigned_user_id == for_user.id)
                | (Routine.assigned_user_id.is_(None))
            )
        rows = (await db.execute(q)).scalars().all()
        return list(rows)

    @staticmethod
    async def get_routine_or_404(
        db: AsyncSession, family_id: UUID, routine_id: UUID
    ) -> Routine:
        q = (
            select(Routine)
            .where(Routine.id == routine_id, Routine.family_id == family_id)
            .options(selectinload(Routine.steps))
        )
        routine = (await db.execute(q)).scalar_one_or_none()
        if routine is None:
            raise NotFoundException("Routine not found")
        return routine

    @staticmethod
    async def update_routine(
        db: AsyncSession,
        family_id: UUID,
        routine_id: UUID,
        *,
        fields: dict,
    ) -> Routine:
        routine = await RoutineService.get_routine_or_404(
            db, family_id, routine_id
        )
        if "name" in fields:
            name = (fields["name"] or "").strip()
            if not name:
                raise ValidationException("Routine name is required")
            routine.name = name[:120]
        if "name_es" in fields:
            routine.name_es = (fields["name_es"] or "").strip()[:120] or None
        if "icon" in fields:
            routine.icon = _norm_icon(fields["icon"], routine.icon)
        if "color" in fields:
            routine.color = (fields["color"] or "").strip()[:9] or None
        if "time_of_day" in fields and fields["time_of_day"] is not None:
            if fields["time_of_day"] not in TIME_OF_DAY_VALUES:
                raise ValidationException("Invalid time_of_day")
            routine.time_of_day = fields["time_of_day"]
        if "assigned_user_id" in fields:
            aid = fields["assigned_user_id"]
            if aid is not None:
                await RoutineService._verify_member(db, family_id, aid)
            routine.assigned_user_id = aid
        if "points_reward" in fields and fields["points_reward"] is not None:
            if int(fields["points_reward"]) < 0:
                raise ValidationException("points_reward must be >= 0")
            routine.points_reward = int(fields["points_reward"])
        if "sort_order" in fields and fields["sort_order"] is not None:
            routine.sort_order = int(fields["sort_order"])
        if "is_active" in fields and fields["is_active"] is not None:
            routine.is_active = bool(fields["is_active"])
        await db.commit()
        return await RoutineService.get_routine_or_404(db, family_id, routine_id)

    @staticmethod
    async def delete_routine(
        db: AsyncSession, family_id: UUID, routine_id: UUID
    ) -> None:
        routine = await RoutineService.get_routine_or_404(
            db, family_id, routine_id
        )
        await db.delete(routine)
        await db.commit()

    # ─── Step authoring ──────────────────────────────────────────────

    @staticmethod
    async def add_step(
        db: AsyncSession,
        family_id: UUID,
        routine_id: UUID,
        *,
        label: str,
        label_es: Optional[str] = None,
        icon: Optional[str] = None,
        sort_order: Optional[int] = None,
    ) -> RoutineStep:
        routine = await RoutineService.get_routine_or_404(
            db, family_id, routine_id
        )
        label = (label or "").strip()
        if not label:
            raise ValidationException("Step label is required")
        if sort_order is None:
            sort_order = (
                max((s.sort_order for s in routine.steps), default=-1) + 1
            )
        step = RoutineStep(
            routine_id=routine.id,
            label=label[:120],
            label_es=(label_es or "").strip()[:120] or None,
            icon=_norm_icon(icon, "✅"),
            sort_order=int(sort_order),
        )
        db.add(step)
        await db.commit()
        await db.refresh(step)
        return step

    @staticmethod
    async def _get_step(
        db: AsyncSession, family_id: UUID, routine_id: UUID, step_id: UUID
    ) -> RoutineStep:
        q = (
            select(RoutineStep)
            .join(Routine, Routine.id == RoutineStep.routine_id)
            .where(
                RoutineStep.id == step_id,
                RoutineStep.routine_id == routine_id,
                Routine.family_id == family_id,
            )
        )
        step = (await db.execute(q)).scalar_one_or_none()
        if step is None:
            raise NotFoundException("Routine step not found")
        return step

    @staticmethod
    async def update_step(
        db: AsyncSession,
        family_id: UUID,
        routine_id: UUID,
        step_id: UUID,
        *,
        fields: dict,
    ) -> RoutineStep:
        step = await RoutineService._get_step(
            db, family_id, routine_id, step_id
        )
        if "label" in fields:
            label = (fields["label"] or "").strip()
            if not label:
                raise ValidationException("Step label is required")
            step.label = label[:120]
        if "label_es" in fields:
            step.label_es = (fields["label_es"] or "").strip()[:120] or None
        if "icon" in fields:
            step.icon = _norm_icon(fields["icon"], step.icon)
        if "sort_order" in fields and fields["sort_order"] is not None:
            step.sort_order = int(fields["sort_order"])
        await db.commit()
        await db.refresh(step)
        return step

    @staticmethod
    async def delete_step(
        db: AsyncSession, family_id: UUID, routine_id: UUID, step_id: UUID
    ) -> None:
        step = await RoutineService._get_step(
            db, family_id, routine_id, step_id
        )
        await db.delete(step)
        await db.commit()

    @staticmethod
    async def reorder_steps(
        db: AsyncSession,
        family_id: UUID,
        routine_id: UUID,
        ordered_step_ids: list[UUID],
    ) -> Routine:
        routine = await RoutineService.get_routine_or_404(
            db, family_id, routine_id
        )
        by_id = {s.id: s for s in routine.steps}
        order = 0
        for sid in ordered_step_ids:
            step = by_id.get(sid if isinstance(sid, UUID) else UUID(str(sid)))
            if step is not None:
                step.sort_order = order
                order += 1
        await db.commit()
        return await RoutineService.get_routine_or_404(db, family_id, routine_id)

    # ─── Authorization helpers ───────────────────────────────────────

    @staticmethod
    async def _verify_member(
        db: AsyncSession, family_id: UUID, user_id: UUID
    ) -> User:
        user = (
            await db.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if user is None or user.family_id != family_id:
            raise ValidationException("Assigned user is not in your family")
        return user

    @staticmethod
    def _may_run(routine: Routine, user: User) -> bool:
        """Whether ``user`` may complete steps on ``routine`` for themselves."""
        if routine.assigned_user_id is None:
            return True  # family-wide: anyone runs their own copy
        return routine.assigned_user_id == user.id

    # ─── Kid / kiosk runner ──────────────────────────────────────────

    @staticmethod
    def _serialize_routine(
        routine: Routine, lang: str, progress: Optional[RoutineProgress]
    ) -> dict:
        done_ids = set(progress.completed_step_ids or []) if progress else set()
        steps_out = []
        for s in sorted(routine.steps, key=lambda x: x.sort_order):
            steps_out.append(
                {
                    "id": str(s.id),
                    "label": s.label,
                    "label_es": s.label_es,
                    "icon": s.icon,
                    "sort_order": s.sort_order,
                    "done": str(s.id) in done_ids,
                }
            )
        total = len(steps_out)
        done = sum(1 for s in steps_out if s["done"])
        return {
            "id": str(routine.id),
            "name": routine.name,
            "name_es": routine.name_es,
            "icon": routine.icon,
            "color": routine.color,
            "time_of_day": routine.time_of_day,
            "assigned_user_id": (
                str(routine.assigned_user_id)
                if routine.assigned_user_id
                else None
            ),
            "points_reward": routine.points_reward,
            "sort_order": routine.sort_order,
            "is_active": routine.is_active,
            "steps": steps_out,
            "total_steps": total,
            "steps_done": done,
            "completed": total > 0 and done == total,
            "awarded": bool(progress.awarded) if progress else False,
        }

    @staticmethod
    async def today_for_user(
        db: AsyncSession, user: User, *, target_user_id: Optional[UUID] = None
    ) -> dict:
        """Active routines the target kid runs today, each with steps + today's
        progress. A PARENT may pass ``target_user_id`` to preview a kid's board;
        anyone else may only see their own.
        """
        target = user
        if target_user_id is not None and target_user_id != user.id:
            if user.role != UserRole.PARENT:
                raise ForbiddenException("You can only view your own routines")
            target = await RoutineService._verify_member(
                db, user.family_id, target_user_id
            )

        today = await RoutineService._user_local_today(db, target)
        routines = await RoutineService.list_routines(
            db, user.family_id, for_user=target, active_only=True
        )
        prog = await RoutineService._progress_map(
            db, [r.id for r in routines], target.id, today
        )
        lang = getattr(target, "preferred_lang", None) or "es"
        color = await RoutineService._member_color(db, target)
        return {
            "date": today.isoformat(),
            "user_id": str(target.id),
            "color": color,
            "routines": [
                RoutineService._serialize_routine(r, lang, prog.get(r.id))
                for r in routines
            ],
        }

    @staticmethod
    async def _progress_map(
        db: AsyncSession, routine_ids: list[UUID], user_id: UUID, day: date
    ) -> dict[UUID, RoutineProgress]:
        if not routine_ids:
            return {}
        q = select(RoutineProgress).where(
            RoutineProgress.routine_id.in_(routine_ids),
            RoutineProgress.user_id == user_id,
            RoutineProgress.completion_date == day,
        )
        rows = (await db.execute(q)).scalars().all()
        return {r.routine_id: r for r in rows}

    @staticmethod
    async def _member_color(db: AsyncSession, user: User) -> str:
        """Per-kid kiosk color — stored member pref if any, else deterministic."""
        from app.services.member_prefs_service import (
            MemberPrefsService,
            color_hex,
            resolve_color_name,
        )

        try:
            prefs = await MemberPrefsService.get_family_prefs(user.family_id)
            name = resolve_color_name(user.id, prefs.get(str(user.id)))
        except Exception:
            from app.services.member_prefs_service import default_color_name

            name = default_color_name(user.id)
        return color_hex(name)

    # ─── Step completion + reward ────────────────────────────────────

    @staticmethod
    async def complete_step(
        db: AsyncSession, user: User, routine_id: UUID, step_id: UUID
    ) -> dict:
        """Mark one step done for the current user TODAY (idempotent).

        When this tap makes EVERY current step done, award ``points_reward``
        POINTS once and feed the pet. Returns the routine's fresh progress plus
        whether this call triggered the reward.
        """
        routine = await RoutineService.get_routine_or_404(
            db, user.family_id, routine_id
        )
        if not routine.is_active:
            raise ValidationException("Routine is not active")
        if not RoutineService._may_run(routine, user):
            raise ForbiddenException("This routine is not assigned to you")

        step = next((s for s in routine.steps if s.id == step_id), None)
        if step is None:
            raise NotFoundException("Routine step not found")

        today = await RoutineService._user_local_today(db, user)
        progress = await RoutineService._get_or_create_progress(
            db, routine.id, user.id, today
        )

        step_ids = set(progress.completed_step_ids or [])
        sid = str(step.id)
        newly_awarded = False
        if sid not in step_ids:
            step_ids.add(sid)
            # Reassign (not in-place mutate) so SQLAlchemy flags the JSONB dirty.
            progress.completed_step_ids = sorted(step_ids)

            current_step_ids = {str(s.id) for s in routine.steps}
            done = len(step_ids & current_step_ids)
            total = len(current_step_ids)
            if not progress.awarded and total > 0 and done >= total:
                progress.awarded = True
                progress.points_awarded = routine.points_reward
                await RoutineService._award_completion(db, routine, user)
                progress.pet_fed = True
                newly_awarded = True

        await db.commit()
        await db.refresh(progress)
        # Re-read the routine so serialization sees committed step set.
        routine = await RoutineService.get_routine_or_404(
            db, user.family_id, routine_id
        )
        lang = getattr(user, "preferred_lang", None) or "es"
        payload = RoutineService._serialize_routine(routine, lang, progress)
        payload["reward_granted"] = newly_awarded
        payload["points_awarded"] = progress.points_awarded if newly_awarded else 0
        return payload

    @staticmethod
    async def _get_or_create_progress(
        db: AsyncSession, routine_id: UUID, user_id: UUID, day: date
    ) -> RoutineProgress:
        q = (
            select(RoutineProgress)
            .where(
                RoutineProgress.routine_id == routine_id,
                RoutineProgress.user_id == user_id,
                RoutineProgress.completion_date == day,
            )
            .with_for_update()
        )
        row = (await db.execute(q)).scalar_one_or_none()
        if row is not None:
            return row
        row = RoutineProgress(
            routine_id=routine_id,
            user_id=user_id,
            completion_date=day,
            completed_step_ids=[],
        )
        db.add(row)
        try:
            await db.flush()
        except IntegrityError:
            # Concurrent first-tap created it — re-read the winner's row.
            await db.rollback()
            row = (
                await db.execute(
                    select(RoutineProgress)
                    .where(
                        RoutineProgress.routine_id == routine_id,
                        RoutineProgress.user_id == user_id,
                        RoutineProgress.completion_date == day,
                    )
                    .with_for_update()
                )
            ).scalar_one()
        return row

    @staticmethod
    async def _award_completion(
        db: AsyncSession, routine: Routine, user: User
    ) -> None:
        """Credit POINTS (privileges — never cash) + feed the pet. No commit —
        folds into complete_step's transaction so the reward and the progress
        flip are atomic."""
        points = int(routine.points_reward or 0)
        if points > 0:
            fresh = await get_user_by_id(db, user.id)
            before = fresh.points
            fresh.points = before + points
            db.add(
                PointTransaction(
                    type=TransactionType.BONUS,
                    user_id=user.id,
                    points=points,
                    balance_before=before,
                    balance_after=fresh.points,
                    description=f"Routine completed: {routine.name}",
                )
            )

        # Feed the pet through the shared hook (best-effort; never breaks the
        # reward). Mandatory magnitude — a routine is a chore-shaped win.
        from app.services.pet_service import PetService

        await PetService.on_task_completed(db, user.id, is_bonus=False)
