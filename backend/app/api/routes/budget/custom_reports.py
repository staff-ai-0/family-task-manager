"""
Custom report routes

CRUD endpoints for saved custom budget reports plus data generation.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from uuid import UUID

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_parent_role
from app.core.type_utils import to_uuid_required
from app.services.budget.custom_report_service import CustomReportService
from app.schemas.budget import CustomReportCreate, CustomReportUpdate, CustomReportResponse
from app.models import User

router = APIRouter()


@router.get("/", response_model=List[CustomReportResponse])
async def list_custom_reports(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all saved custom reports for the family."""
    family_id = to_uuid_required(current_user.family_id)
    return await CustomReportService.list_by_family(db, family_id)


@router.post("/", response_model=CustomReportResponse, status_code=status.HTTP_201_CREATED)
async def create_custom_report(
    data: CustomReportCreate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Create a new custom report configuration (parent only)."""
    family_id = to_uuid_required(current_user.family_id)
    return await CustomReportService.create(
        db,
        family_id=family_id,
        created_by=to_uuid_required(current_user.id),
        data=data,
    )


@router.get("/{report_id}", response_model=CustomReportResponse)
async def get_custom_report(
    report_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a custom report by ID."""
    family_id = to_uuid_required(current_user.family_id)
    return await CustomReportService.get_by_id(db, report_id, family_id)


@router.put("/{report_id}", response_model=CustomReportResponse)
async def update_custom_report(
    report_id: UUID,
    data: CustomReportUpdate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Update a custom report (parent only)."""
    family_id = to_uuid_required(current_user.family_id)
    return await CustomReportService.update(db, report_id, family_id, data)


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_custom_report(
    report_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Delete a custom report (parent only)."""
    family_id = to_uuid_required(current_user.family_id)
    await CustomReportService.delete_by_id(db, report_id, family_id)


@router.get("/{report_id}/data")
async def generate_report_data(
    report_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Execute a saved custom report and return its data."""
    family_id = to_uuid_required(current_user.family_id)
    report = await CustomReportService.get_by_id(db, report_id, family_id)
    return await CustomReportService.generate_data(db, report, family_id)
