"""
Budget Month Locking routes

Endpoints for closing/locking months to prevent modifications to past periods.
"""

from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from datetime import date
from uuid import UUID

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_parent_role
from app.core.type_utils import to_uuid_required
from app.core.exceptions import ValidationError
from app.services.budget.month_locking_service import MonthLockingService
from app.schemas.budget import (
    MonthClosureResponse,
    MonthReopenResponse,
    MonthStatusResponse,
    ClosedMonthInfo,
)
from app.models import User

router = APIRouter()


@router.post("/{year}/{month}/close", response_model=MonthClosureResponse, status_code=status.HTTP_200_OK)
async def close_month(
    year: int,
    month: int,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """
    Close a month to prevent modifications (parent only).
    
    This locks the month, preventing any edits to transactions or allocations.
    """
    # Validate month
    if month < 1 or month > 12:
        raise ValidationError("Month must be between 1 and 12")
    
    # Convert year/month to date (first day of month)
    month_date = date(year, month, 1)
    
    family_id = to_uuid_required(current_user.family_id)
    result = await MonthLockingService.close_month(db, family_id, month_date)
    
    return MonthClosureResponse(**result)


@router.post("/{year}/{month}/reopen", response_model=MonthReopenResponse, status_code=status.HTTP_200_OK)
async def reopen_month(
    year: int,
    month: int,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """
    Reopen a closed month to allow modifications (parent only).
    
    This unlocks the month, allowing edits to transactions and allocations again.
    """
    # Validate month
    if month < 1 or month > 12:
        raise ValidationError("Month must be between 1 and 12")
    
    # Convert year/month to date (first day of month)
    month_date = date(year, month, 1)
    
    family_id = to_uuid_required(current_user.family_id)
    result = await MonthLockingService.reopen_month(db, family_id, month_date)
    
    return MonthReopenResponse(**result)


@router.get("/{year}/{month}/status", response_model=MonthStatusResponse)
async def get_month_status(
    year: int,
    month: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get the closure status of a specific month.
    
    Returns whether the month is locked and when it was locked.
    """
    # Validate month
    if month < 1 or month > 12:
        raise ValidationError("Month must be between 1 and 12")
    
    # Convert year/month to date (first day of month)
    month_date = date(year, month, 1)
    
    family_id = to_uuid_required(current_user.family_id)
    status_info = await MonthLockingService.get_month_status(db, family_id, month_date)
    
    return MonthStatusResponse(**status_info)


@router.get("/closed", response_model=List[ClosedMonthInfo])
async def list_closed_months(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=100, description="Maximum number of months to return"),
    offset: int = Query(0, ge=0, description="Number of months to skip"),
):
    """
    List all closed months for the family.
    
    Returns the most recent closed months first.
    """
    family_id = to_uuid_required(current_user.family_id)
    closed_months = await MonthLockingService.get_closed_months(
        db, family_id, limit=limit, offset=offset
    )
    
    return [ClosedMonthInfo(**month) for month in closed_months]
