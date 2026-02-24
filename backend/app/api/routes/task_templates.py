"""
Task template management routes

Handles CRUD operations for reusable task templates (parent only).
Includes auto-translation endpoint for bilingual support.
"""

import logging
from fastapi import APIRouter, Depends, status, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from uuid import UUID

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_parent_role
from app.core.type_utils import to_uuid_required
from app.services.task_template_service import TaskTemplateService
from app.services.translation_service import TranslationService
from app.schemas.task_template import (
    TaskTemplateCreate,
    TaskTemplateUpdate,
    TaskTemplateResponse,
    TranslateRequest,
    TranslateResponse,
)
from app.models import User

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/", response_model=List[TaskTemplateResponse])
async def list_templates(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    is_bonus: Optional[bool] = Query(None, description="Filter by bonus status"),
):
    """List all task templates for the family"""
    templates = await TaskTemplateService.list_templates(
        db,
        family_id=to_uuid_required(current_user.family_id),
        is_active=is_active,
        is_bonus=is_bonus,
    )
    return templates


@router.post("/", response_model=TaskTemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_template(
    data: TaskTemplateCreate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Create a new task template (parent only)"""
    template = await TaskTemplateService.create_template(
        db,
        data,
        family_id=to_uuid_required(current_user.family_id),
        created_by=to_uuid_required(current_user.id),
    )
    return template


@router.get("/{template_id}", response_model=TaskTemplateResponse)
async def get_template(
    template_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a task template by ID"""
    template = await TaskTemplateService.get_template(
        db, template_id, to_uuid_required(current_user.family_id)
    )
    return template


@router.put("/{template_id}", response_model=TaskTemplateResponse)
async def update_template(
    template_id: UUID,
    data: TaskTemplateUpdate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Update a task template (parent only)"""
    template = await TaskTemplateService.update_template(
        db, template_id, data, to_uuid_required(current_user.family_id)
    )
    return template


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Delete a task template (parent only, cascades to assignments)"""
    await TaskTemplateService.delete_template(
        db, template_id, to_uuid_required(current_user.family_id)
    )
    return None


@router.patch("/{template_id}/toggle", response_model=TaskTemplateResponse)
async def toggle_template(
    template_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Toggle a template active/inactive (parent only)"""
    template = await TaskTemplateService.toggle_active(
        db, template_id, to_uuid_required(current_user.family_id)
    )
    return template


@router.post("/{template_id}/translate", response_model=TranslateResponse)
async def translate_template(
    template_id: UUID,
    request: TranslateRequest,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """
    Auto-translate a template's title and description using LiteLLM proxy (parent only).
    Does NOT save the translation — returns it for review before saving via PUT.
    """
    template = await TaskTemplateService.get_template(
        db, template_id, to_uuid_required(current_user.family_id)
    )

    # Determine source text based on source_lang
    if request.source_lang == "en":
        source_title = template.title
        source_description = template.description
    else:
        source_title = template.title_es
        source_description = template.description_es

    if not source_title:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Template has no {request.source_lang} title to translate from",
        )

    try:
        result = await TranslationService.translate_template_fields(
            title=source_title,
            description=source_description,
            source_lang=request.source_lang,
            target_lang=request.target_lang,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Translation failed for template {template_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Translation service failed. Please try again.",
        )

    return TranslateResponse(
        title=result["title"],
        description=result["description"],
        source_lang=request.source_lang,
        target_lang=request.target_lang,
    )
