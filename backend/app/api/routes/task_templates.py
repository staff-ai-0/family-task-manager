"""
Task template management routes

Handles CRUD operations for reusable task templates (parent only).
Includes auto-translation endpoint for bilingual support.
"""

import logging
from fastapi import APIRouter, Depends, File, status, Query, HTTPException, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from uuid import UUID

from app.core.database import get_db
from app.core.exceptions import ValidationError
from app.core.dependencies import get_current_user, require_parent_role
from app.core.premium import require_feature
from app.core.rate_limiter import limiter, AI_LIMIT
from app.core.type_utils import to_uuid_required
from app.core.upload_validation import ALLOWED_SCAN_TYPES, MAX_SCAN_BYTES, read_upload_capped
from app.models.user import APPROVAL_APPROVED
from app.services.chart_scanner_service import Member, fold, scan_chore_chart
from app.services.family_service import FamilyService
from app.services.task_template_service import TaskTemplateService
from app.services.translation_service import TranslationService
from app.schemas.task_template import (
    TaskTemplateCreate,
    TaskTemplateUpdate,
    TaskTemplateResponse,
    TranslateRequest,
    TranslateTextRequest,
    TranslateResponse,
    ScanChartResponse,
    ScannedChoreOut,
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


@router.post("/scan-chart", response_model=ScanChartResponse)
@limiter.limit(AI_LIMIT)
async def scan_chart(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """UX-E1: read a chore chart (or list) photo into proposed recurring
    chores. Returns proposals for the parent to review; nothing is stored —
    the browser creates the ticked ones through POST /api/task-templates/."""
    # Plan gate BEFORE the upload is read: this burns LLM tokens.
    await require_feature("ai_features", db, current_user)
    if file.content_type not in ALLOWED_SCAN_TYPES:
        raise HTTPException(status_code=415, detail=f"Unsupported file type: {file.content_type}")
    payload = await read_upload_capped(file, MAX_SCAN_BYTES)
    if not payload:
        raise HTTPException(status_code=400, detail="Empty file")

    family_id = to_uuid_required(current_user.family_id)
    # Participating members only: a deactivated account or a join-code signup
    # still awaiting approval must not be matched (nor shown to the model).
    members = [
        Member(m.id, m.name, str(getattr(m.role, "value", m.role)).lower())
        for m in await FamilyService.get_family_members(db, family_id)
        if m.is_active and m.approval_status == APPROVAL_APPROVED
    ]
    existing = {
        fold(t.title): t.id
        for t in await TaskTemplateService.list_templates(db, family_id, is_active=True)
    }
    try:
        result = await scan_chore_chart(payload, file.content_type, members, existing, current_user.preferred_lang or "es")
    except ValidationError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return ScanChartResponse(
        doc_type=result.doc_type,
        confidence=result.confidence,
        chores=[
            ScannedChoreOut(
                title=c.title, points=c.points, is_bonus=c.is_bonus, days_of_week=c.days_of_week,
                assignee_names=c.assignee_names, assigned_user_ids=c.assigned_user_ids,
                unmatched_names=c.unmatched_names, duplicate_of=c.duplicate_of, description=c.description,
            )
            for c in result.chores
        ],
    )


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


@router.post("/translate-text", response_model=TranslateResponse)
@limiter.limit(AI_LIMIT)
async def translate_text(
    request: Request,
    data: TranslateTextRequest,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """
    Stateless auto-translation of arbitrary title/description text (parent only,
    premium-gated).

    Translates the text carried in the request body — so the editor can translate
    an in-progress edit before it is saved, and the create flow can translate
    before the template row exists. Does NOT persist anything.
    """
    # Same-language request is a no-op — echo the input back without a proxy call.
    # No LLM work happens, so it is neither rate-limited in spirit nor gated.
    if data.source_lang == data.target_lang:
        return TranslateResponse(
            title=data.title,
            description=data.description,
            source_lang=data.source_lang,
            target_lang=data.target_lang,
        )

    # Every LLM call site is premium-gated (mirrors /{id}/translate above).
    await require_feature("ai_features", db, current_user)

    try:
        result = await TranslationService.translate_template_fields(
            title=data.title,
            description=data.description,
            source_lang=data.source_lang,
            target_lang=data.target_lang,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Stateless text translation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Translation service failed. Please try again.",
        )

    return TranslateResponse(
        title=result["title"],
        description=result["description"],
        source_lang=data.source_lang,
        target_lang=data.target_lang,
    )


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
    await require_feature("ai_features", db, current_user)
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
