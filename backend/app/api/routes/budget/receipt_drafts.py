"""
Receipt Draft routes — HITL review queue.

Parents list, approve, or reject low-confidence receipt scans.
"""

import os

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from uuid import UUID

from app.core.database import get_db
from app.core.dependencies import require_parent_role
from app.core.thumbnails import thumb_filename
from app.core.type_utils import to_uuid_required
from app.services.budget.receipt_draft_service import ReceiptDraftService
from app.services.budget.receipt_scanner_service import RECEIPT_UPLOADS_DIR
from app.schemas.budget import ReceiptDraftApprove, ReceiptDraftResponse
from app.models import User

router = APIRouter()


@router.get("/", response_model=List[ReceiptDraftResponse])
async def list_receipt_drafts(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """List all pending receipt drafts for the family (parent only)."""
    return await ReceiptDraftService.list_pending(
        db, to_uuid_required(current_user.family_id)
    )


@router.get("/count")
async def pending_drafts_count(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Return count of pending receipt drafts — used by the nav badge."""
    count = await ReceiptDraftService.pending_count(
        db, to_uuid_required(current_user.family_id)
    )
    return {"count": count}


@router.get("/{draft_id}/image")
async def get_receipt_draft_image(
    draft_id: UUID,
    size: Optional[str] = Query(
        None,
        description="Pass `thumb` for the ~200px WebP thumbnail (falls back to "
        "the full image if none exists).",
    ),
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Serve the stored receipt image for a draft (parent only).

    Family scoping runs through ReceiptDraftService.get_by_id, so `?size=thumb`
    is authorized identically to the full image.
    """
    draft = await ReceiptDraftService.get_by_id(
        db, draft_id, to_uuid_required(current_user.family_id)
    )
    if not draft.image_url:
        raise HTTPException(status_code=404, detail="No image stored for this draft")

    # UUID-named files are immutable → cache aggressively (still private/auth-gated).
    immutable_cache = "private, max-age=31536000, immutable"

    if size == "thumb":
        thumb_path = os.path.join(RECEIPT_UPLOADS_DIR, thumb_filename(f"{draft_id}.jpg"))
        if os.path.exists(thumb_path):
            return FileResponse(
                thumb_path,
                media_type="image/webp",
                headers={"Cache-Control": immutable_cache},
            )

    img_path = os.path.join(RECEIPT_UPLOADS_DIR, f"{draft_id}.jpg")
    if not os.path.exists(img_path):
        raise HTTPException(status_code=404, detail="Image file not found")
    return FileResponse(
        img_path,
        media_type="image/jpeg",
        headers={"Cache-Control": immutable_cache},
    )


@router.get("/{draft_id}", response_model=ReceiptDraftResponse)
async def get_receipt_draft(
    draft_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Get a single receipt draft by ID (parent only)."""
    return await ReceiptDraftService.get_by_id(
        db, draft_id, to_uuid_required(current_user.family_id)
    )


@router.post("/{draft_id}/approve", status_code=status.HTTP_200_OK)
async def approve_receipt_draft(
    draft_id: UUID,
    data: ReceiptDraftApprove,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Approve a receipt draft, optionally correcting extracted fields.

    Creates a real transaction from the (corrected) scan data and marks
    the draft as approved. Any field left null falls back to the
    AI-extracted value.
    """
    return await ReceiptDraftService.approve(
        db, draft_id, to_uuid_required(current_user.family_id), data,
        user_id=current_user.id,
    )


@router.delete("/{draft_id}", status_code=status.HTTP_204_NO_CONTENT)
async def reject_receipt_draft(
    draft_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Reject a receipt draft — no transaction is created (parent only)."""
    await ReceiptDraftService.reject(
        db, draft_id, to_uuid_required(current_user.family_id)
    )
