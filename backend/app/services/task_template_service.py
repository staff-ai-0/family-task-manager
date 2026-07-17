"""
TaskTemplate Service

Business logic for task template management (CRUD).
Templates are permanent, reusable definitions — parents create and manage them.
"""

import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from typing import List, Optional
from uuid import UUID

from app.models.task_template import TaskTemplate
from app.schemas.task_template import TaskTemplateCreate, TaskTemplateUpdate
from app.core.exceptions import ValidationException
from app.services.base_service import BaseFamilyService
from app.services.translation_service import TranslationService

logger = logging.getLogger(__name__)


class TaskTemplateService(BaseFamilyService[TaskTemplate]):
    """Service for task template operations"""

    model = TaskTemplate

    @staticmethod
    def _validate_recurrence(mode: str, every_n: int | None) -> None:
        """since_completion mode needs its N; weekly ignores it."""
        if mode == "since_completion":
            if not every_n or not (1 <= int(every_n) <= 90):
                raise ValidationException(
                    "recur_every_n_days (1-90) is required when "
                    "recurrence_mode=since_completion"
                )

    @staticmethod
    async def create_template(
        db: AsyncSession,
        data: TaskTemplateCreate,
        family_id: UUID,
        created_by: UUID,
    ) -> TaskTemplate:
        """Create a new task template"""
        # Validate interval_days is sensible
        if data.interval_days not in (1, 2, 3, 4, 5, 6, 7):
            raise ValidationException("interval_days must be between 1 and 7")

        TaskTemplateService._validate_recurrence(
            data.recurrence_mode, data.recur_every_n_days
        )

        # Duplicate guard: an ACTIVE template with the same title in this
        # family doubles the chore in every future shuffle (prod once had two
        # live 'Wash Dishes'). Case-insensitive; inactive titles are reusable.
        dup = (await db.execute(
            select(TaskTemplate.id).where(
                and_(
                    TaskTemplate.family_id == family_id,
                    TaskTemplate.is_active == True,  # noqa: E712
                    func.lower(TaskTemplate.title) == data.title.strip().lower(),
                )
            ).limit(1)
        )).scalar_one_or_none()
        if dup is not None:
            raise ValidationException(
                f"Ya existe una tarea activa llamada '{data.title}' — edítala o "
                f"desactívala primero / An active task named '{data.title}' "
                "already exists — edit or deactivate it first"
            )

        title_es = data.title_es
        description_es = data.description_es

        # Best-effort auto-translate to ES when blank. Failures are non-fatal —
        # template still saves without ES, parent can fill manually later.
        # AI is paid-only: free families skip the LLM call silently.
        from app.core.premium import family_tier_allows
        if not title_es and await family_tier_allows(db, family_id, "ai_features"):
            try:
                translated = await TranslationService.translate_template_fields(
                    title=data.title,
                    description=data.description if not description_es else None,
                    source_lang="en",
                    target_lang="es",
                )
                title_es = translated["title"]
                if not description_es and translated.get("description"):
                    description_es = translated["description"]
            except Exception as e:
                logger.warning(
                    "Auto-translate failed on template create (family=%s): %s",
                    family_id,
                    e,
                )

        template = TaskTemplate(
            title=data.title,
            description=data.description,
            title_es=title_es,
            description_es=description_es,
            points=data.points,
            effort_level=data.effort_level,
            interval_days=data.interval_days,
            days_of_week=data.days_of_week,
            recurrence_mode=data.recurrence_mode,
            recur_every_n_days=(
                data.recur_every_n_days
                if data.recurrence_mode == "since_completion"
                else None
            ),
            requires_proof=data.requires_proof,
            assignment_type=data.assignment_type,
            assigned_user_ids=(
                [str(u) for u in data.assigned_user_ids]
                if data.assigned_user_ids
                else None
            ),
            allowed_roles=(
                [r.lower() for r in data.allowed_roles]
                if data.allowed_roles
                else None
            ),
            is_bonus=data.is_bonus,
            auto_late_penalty=data.auto_late_penalty,
            late_restriction_type=data.late_restriction_type,
            late_severity=data.late_severity,
            late_duration_days=data.late_duration_days,
            blocks_rewards=data.blocks_rewards,
            gig_mode=data.gig_mode.value if hasattr(data.gig_mode, "value") else data.gig_mode,
            collaboration_min_count=data.collaboration_min_count,
            created_by=created_by,
            family_id=family_id,
        )

        db.add(template)
        await db.commit()
        await db.refresh(template)
        try:
            from app.services.onboarding_service import OnboardingService
            await OnboardingService.advance(family_id, "task_created", db)
            await db.commit()
        except Exception:
            logger.warning("onboarding advance task_created failed", exc_info=True)

        # since_completion templates aren't part of the weekly shuffle — spawn
        # the first assignment right away so the kid sees it today instead of
        # waiting for the next hourly sweep. Best-effort.
        if template.recurrence_mode == "since_completion" and template.is_active:
            try:
                from app.services.task_assignment_service import (
                    TaskAssignmentService,
                )
                await TaskAssignmentService.spawn_interval_assignments_for_family(
                    db, family_id
                )
            except Exception:
                logger.warning(
                    "initial interval spawn failed (family=%s)", family_id,
                    exc_info=True,
                )
        return template

    @staticmethod
    async def get_template(
        db: AsyncSession, template_id: UUID, family_id: UUID
    ) -> TaskTemplate:
        """Get a template by ID"""
        return await TaskTemplateService.get_by_id(db, template_id, family_id)

    @staticmethod
    async def list_templates(
        db: AsyncSession,
        family_id: UUID,
        is_active: Optional[bool] = None,
        is_bonus: Optional[bool] = None,
    ) -> List[TaskTemplate]:
        """List templates with optional filters"""
        query = select(TaskTemplate).where(TaskTemplate.family_id == family_id)

        if is_active is not None:
            query = query.where(TaskTemplate.is_active == is_active)
        if is_bonus is not None:
            query = query.where(TaskTemplate.is_bonus == is_bonus)

        query = query.order_by(TaskTemplate.created_at.desc())
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def update_template(
        db: AsyncSession,
        template_id: UUID,
        data: TaskTemplateUpdate,
        family_id: UUID,
    ) -> TaskTemplate:
        """Update a template"""
        update_fields = data.model_dump(exclude_unset=True)

        # Validate interval_days if provided
        if "interval_days" in update_fields:
            if update_fields["interval_days"] not in (1, 2, 3, 4, 5, 6, 7):
                raise ValidationException("interval_days must be between 1 and 7")

        # Validate the RESULTING recurrence combination (mode may come from
        # the update while N stays on the row, or vice versa).
        if "recurrence_mode" in update_fields or "recur_every_n_days" in update_fields:
            current = await TaskTemplateService.get_by_id(db, template_id, family_id)
            mode = update_fields.get("recurrence_mode", current.recurrence_mode)
            every_n = update_fields.get(
                "recur_every_n_days", current.recur_every_n_days
            )
            TaskTemplateService._validate_recurrence(mode, every_n)
            if mode != "since_completion":
                update_fields["recur_every_n_days"] = None

        # Normalize allowed_roles to lowercase strings (or None to clear)
        if "allowed_roles" in update_fields:
            roles = update_fields["allowed_roles"]
            update_fields["allowed_roles"] = (
                [r.lower() for r in roles] if roles else None
            )

        # Normalize assigned_user_ids to JSONB-safe string list
        if "assigned_user_ids" in update_fields:
            uids = update_fields["assigned_user_ids"]
            update_fields["assigned_user_ids"] = (
                [str(u) for u in uids] if uids else None
            )

        # Validate the RESULTING assignment configuration: FIXED without a
        # member list has no possible assignee and the shuffle would skip it.
        if "assignment_type" in update_fields or "assigned_user_ids" in update_fields:
            current = await TaskTemplateService.get_by_id(db, template_id, family_id)
            final_type = update_fields.get("assignment_type", current.assignment_type)
            final_type = getattr(final_type, "value", final_type)
            final_ids = update_fields.get(
                "assigned_user_ids", current.assigned_user_ids
            )
            if str(final_type).lower() == "fixed" and not final_ids:
                raise ValidationException(
                    "Una tarea fija necesita al menos un miembro asignado / "
                    "A fixed task needs at least one assigned member"
                )

        return await TaskTemplateService.update_by_id(
            db, template_id, family_id, update_fields
        )

    @staticmethod
    async def delete_template(
        db: AsyncSession, template_id: UUID, family_id: UUID
    ) -> None:
        """Delete a template (cascades to assignments)"""
        await TaskTemplateService.delete_by_id(db, template_id, family_id)

    @staticmethod
    async def toggle_active(
        db: AsyncSession, template_id: UUID, family_id: UUID
    ) -> TaskTemplate:
        """Toggle template active/inactive status"""
        template = await TaskTemplateService.get_by_id(db, template_id, family_id)
        template.is_active = not template.is_active
        await db.commit()
        await db.refresh(template)
        return template
