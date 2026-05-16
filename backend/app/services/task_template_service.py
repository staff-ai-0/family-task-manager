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
from app.core.exceptions import NotFoundException, ValidationException
from app.services.base_service import BaseFamilyService
from app.services.translation_service import TranslationService

logger = logging.getLogger(__name__)


class TaskTemplateService(BaseFamilyService[TaskTemplate]):
    """Service for task template operations"""

    model = TaskTemplate

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

        title_es = data.title_es
        description_es = data.description_es

        # Best-effort auto-translate to ES when blank. Failures are non-fatal —
        # template still saves without ES, parent can fill manually later.
        if not title_es:
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
            interval_days=data.interval_days,
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
            created_by=created_by,
            family_id=family_id,
        )

        db.add(template)
        await db.commit()
        await db.refresh(template)
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
