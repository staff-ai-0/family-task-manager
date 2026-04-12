"""
Receipt Draft routes — HITL review queue.

Parents list, approve, or reject low-confidence receipt scans.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from uuid import UUID

from app.core.database import get_db
from app.core.dependencies import require_parent_role
from app.core.type_utils import to_uuid_required
from app.services.budget.receipt_draft_service import ReceiptDraftService
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
        db, draft_id, to_uuid_required(current_user.family_id), data
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
