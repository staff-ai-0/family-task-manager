"""
Family management routes

Handles family CRUD operations, member management, and statistics.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from uuid import UUID

from app.core.database import get_db
from app.core.dependencies import get_current_user, verify_family_id, require_parent_role
from app.core.rate_limiter import limiter
from app.core.type_utils import to_uuid_required
from app.services import FamilyService
from app.services.family_deletion_service import FamilyDeletionService
from app.services.family_export_service import FamilyExportService
from app.schemas.family import (
    FamilyCreate,
    FamilyDeleteRequest,
    FamilyUpdate,
    FamilyResponse,
    FamilyWithMembers,
    FamilyStats,
)
from app.schemas.user import UserResponse
from app.models import User

router = APIRouter()

# The full-family export loads every domain into memory and zips it — strict
# per-IP limit so it cannot be used to hammer the DB / exhaust backend memory.
EXPORT_RATE_LIMIT = "3/hour"


@router.get("/me", response_model=FamilyWithMembers)
async def get_my_family(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get current user's family with members"""
    family = await FamilyService.get_family(
        db, to_uuid_required(current_user.family_id)
    )
    members = await FamilyService.get_family_members(
        db, to_uuid_required(current_user.family_id)
    )
    return FamilyWithMembers(
        **family.__dict__, members=[UserResponse.model_validate(m) for m in members]
    )


@router.post("/", response_model=FamilyResponse, status_code=status.HTTP_201_CREATED)
async def create_family(
    family_data: FamilyCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new family"""
    family = await FamilyService.create_family(
        db, family_data, to_uuid_required(current_user.id)
    )
    return family


@router.get("/members", response_model=List[UserResponse])
async def get_my_family_members(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Members of caller's own family. Path before /{family_id} so 'members'
    isn't parsed as a UUID."""
    return await FamilyService.get_family_members(
        db, to_uuid_required(current_user.family_id)
    )


@router.get("/export")
@limiter.limit(EXPORT_RATE_LIMIT)
async def export_my_family(
    request: Request,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Download a ZIP with ALL of the caller's family data (parent only).

    JSON dumps per domain + a re-importable budget backup. Uploaded images
    are listed in a manifest, not bundled. Path is declared before
    /{family_id} so 'export' isn't parsed as a UUID.

    Rate limited (EXPORT_RATE_LIMIT) and size guarded (413 past the caps in
    family_export_service) because the archive is built fully in memory.
    """
    zip_bytes = await FamilyExportService.export_family(
        db, to_uuid_required(current_user.family_id)
    )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="family-export-{stamp}.zip"',
        },
    )


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_family(
    payload: FamilyDeleteRequest,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Close the caller's family — soft delete (parent only).

    Re-auth required: password accounts send ``password``; Google-only
    accounts send ``confirm_name`` (the exact family name). Cancels any live
    PayPal subscription, stamps ``deleted_at`` on the family + every member,
    and invalidates their sessions — auth 401s ('account closed') immediately.
    Data is retained for a 30-day grace window (so the export taken beforehand
    stays valid and a mistake is recoverable) and hard-purged by the daily
    purge sweep afterwards. This is the account-deletion path for the last
    parent (self-deletion via DELETE /api/users/{id} stays blocked).
    """
    await FamilyDeletionService.delete_family(
        db,
        family_id=to_uuid_required(current_user.family_id),
        requesting_user=current_user,
        password=payload.password,
        confirm_name=payload.confirm_name,
    )
    return None


@router.get("/{family_id}", response_model=FamilyResponse)
async def get_family(
    family_id: UUID = Depends(verify_family_id),
    db: AsyncSession = Depends(get_db),
):
    """Get family by ID"""
    family = await FamilyService.get_family(db, family_id)
    return family


@router.put("/{family_id}", response_model=FamilyResponse)
async def update_family(
    family_data: FamilyUpdate,
    family_id: UUID = Depends(verify_family_id),
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Update family information (parent only — non-parents can shift
    family-wide settings like timezone otherwise, bypassing gig gating)."""
    family = await FamilyService.update_family(db, family_id, family_data)
    return family


@router.patch("/me", response_model=FamilyResponse)
async def update_my_family(
    family_data: FamilyUpdate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Parent-only update of the caller's own family (name, timezone, etc.)."""
    family = await FamilyService.update_family(
        db, to_uuid_required(current_user.family_id), family_data
    )
    return family


@router.get("/{family_id}/members", response_model=List[UserResponse])
async def get_family_members(
    family_id: UUID = Depends(verify_family_id),
    db: AsyncSession = Depends(get_db),
):
    """Get all family members"""
    members = await FamilyService.get_family_members(db, family_id)
    return members


@router.get("/{family_id}/stats", response_model=FamilyStats)
async def get_family_stats(
    family_id: UUID = Depends(verify_family_id),
    db: AsyncSession = Depends(get_db),
):
    """Get family statistics"""
    stats = await FamilyService.get_family_stats(db, family_id)
    return stats


# --- Join Code Endpoints ---

@router.post("/join-code/generate")
async def generate_join_code(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Generate or regenerate a family join code (parent only)"""
    family_id = to_uuid_required(current_user.family_id)
    code = await FamilyService.generate_join_code(db, family_id)
    return {"join_code": code}


@router.get("/join-code/current")
async def get_join_code(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Get the current family join code (parent only)"""
    family_id = to_uuid_required(current_user.family_id)
    family = await FamilyService.get_family(db, family_id)
    return {"join_code": family.join_code}
