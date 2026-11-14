"""Chore baseline photo endpoints (parent only). HTTP only; logic in BaselineService.

Mounted at /api/task-templates BEFORE the task_templates router so the static
``/baselines/status`` path can never be read as a ``/{template_id}``."""
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_parent_role
from app.core.type_utils import to_uuid_required
from app.core.upload_validation import MAX_PROOF_BYTES, read_upload_capped
from app.models.user import User
from app.schemas.baseline import BaselineOut, BaselineStatusRow
from app.services.baseline_service import BaselineService

router = APIRouter()


@router.get("/baselines/status", response_model=List[BaselineStatusRow])
async def baselines_status(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    return await BaselineService.status(db, to_uuid_required(current_user.family_id))


@router.get("/{template_id}/baselines", response_model=List[BaselineOut])
async def list_baselines(
    template_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    return await BaselineService.list(db, to_uuid_required(current_user.family_id), template_id)


@router.post("/{template_id}/baselines", response_model=BaselineOut, status_code=status.HTTP_201_CREATED)
async def upload_baseline(
    template_id: UUID,
    file: UploadFile = File(..., description="Baseline image (JPEG, PNG, WebP). Max 15MB."),
    caption: Optional[str] = Form(None, max_length=120),
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    body = await read_upload_capped(file, MAX_PROOF_BYTES)
    return await BaselineService.add(
        db, current_user, template_id, body, file.content_type or "", caption
    )


@router.delete("/{template_id}/baselines/{baseline_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_baseline(
    template_id: UUID,
    baseline_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    await BaselineService.delete(db, to_uuid_required(current_user.family_id), template_id, baseline_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
