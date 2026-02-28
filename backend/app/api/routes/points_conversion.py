"""
Points Conversion Routes

Handles manual point-to-money conversions for TEEN/CHILD users.
Conversions are based on weekly task completion percentages.

Conversion Rules (based on entire week's tasks):
- 100% completion (all default + bonus tasks): 100% of points convertible
- 100% default tasks only: 80% of points convertible  
- ≥80% default tasks: 50% of points convertible
- <80% default tasks: 0% (conversion blocked)

Money Distribution:
- 85% → Checking/Cash account (spendable)
- 15% → Savings account (locked)
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from pydantic import BaseModel
from typing import Optional
from datetime import date
from uuid import UUID
import os
import httpx

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.type_utils import to_uuid_required
from app.models import User
from app.models.user import UserRole
from app.services.task_assignment_service import TaskAssignmentService

router = APIRouter()

# Configuration
FINANCE_API_URL = os.getenv("FINANCE_API_URL", "http://finance-api:5007")
POINTS_TO_MONEY_RATE = float(os.getenv("POINTS_TO_MONEY_RATE", "0.10"))
CURRENCY = os.getenv("POINTS_TO_MONEY_CURRENCY", "MXN")


# ─── Request/Response Schemas ───────────────────────────────────────

class PointConversionRequest(BaseModel):
    """Request to convert points to money."""
    points: int


class PointConversionResponse(BaseModel):
    """Response with conversion details."""
    success: bool
    points_converted: int
    money_amount: float
    currency: str
    checking_amount: float
    savings_amount: float
    new_points_balance: int
    completion_percentage: int
    max_convertible_points: int
    checking_transaction_id: str
    savings_transaction_id: str


class ConversionEligibilityResponse(BaseModel):
    """Response showing conversion eligibility without performing conversion."""
    eligible: bool
    current_points: int
    max_convertible_points: int
    max_convertible_amount: float
    completion_percentage: int
    required_completed: int
    required_total: int
    bonus_completed: int
    bonus_total: int
    reason: str


# ─── Helper Functions ───────────────────────────────────────────────

def calculate_conversion_limit(
    required_completed: int,
    required_total: int,
    bonus_completed: int,
    bonus_total: int,
) -> tuple[int, str]:
    """
    Calculate the percentage of points that can be converted based on task completion.
    
    Returns:
        (conversion_percentage, reason)
    """
    if required_total == 0:
        return (0, "No tasks assigned this week")
    
    # Calculate required task completion percentage
    required_pct = (required_completed / required_total) * 100 if required_total > 0 else 0
    
    # Check completion levels
    if required_pct < 80:
        return (0, "Need 80% default task completion to convert points")
    
    # Check if ALL default tasks completed
    if required_completed >= required_total:
        # All default tasks done - check bonus
        if bonus_total > 0 and bonus_completed >= bonus_total:
            # All default + all bonus tasks = 100% conversion
            return (100, "All tasks completed! Full conversion available")
        else:
            # All default only = 80% conversion
            return (80, "Default tasks completed (bonus tasks remaining)")
    
    # 80-99% default tasks = 50% conversion
    return (50, f"{int(required_pct)}% default tasks completed")


async def get_week_task_completion(
    db: AsyncSession,
    user_id: UUID,
    family_id: UUID,
) -> dict:
    """Get task completion stats for the current week."""
    # Get Monday of current week
    today = date.today()
    days_since_monday = today.weekday()
    week_of = today - (days_since_monday * date.resolution)
    
    # Get all assignments for the week
    assignments = await TaskAssignmentService.list_assignments_for_week(
        db,
        family_id=family_id,
        week_of=week_of,
        user_id=user_id,
    )
    
    # Separate required and bonus tasks
    from app.models.task_assignment import AssignmentStatus
    
    required_assignments = [a for a in assignments if not a.template.is_bonus]
    bonus_assignments = [a for a in assignments if a.template.is_bonus]
    
    required_completed = sum(
        1 for a in required_assignments if a.status == AssignmentStatus.COMPLETED
    )
    bonus_completed = sum(
        1 for a in bonus_assignments if a.status == AssignmentStatus.COMPLETED
    )
    
    return {
        "required_total": len(required_assignments),
        "required_completed": required_completed,
        "bonus_total": len(bonus_assignments),
        "bonus_completed": bonus_completed,
        "assignments": assignments,
    }


# ─── Routes ──────────────────────────────────────────────────────────

@router.get("/eligibility", response_model=ConversionEligibilityResponse)
async def get_conversion_eligibility(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Check conversion eligibility without performing the conversion.
    Shows max convertible points based on weekly task completion.
    """
    # Only TEEN and CHILD users can convert points
    if current_user.role not in [UserRole.TEEN, UserRole.CHILD]:
        raise HTTPException(
            status_code=403,
            detail="Only children can convert points to money"
        )
    
    # Get weekly task completion
    progress = await get_week_task_completion(
        db,
        user_id=to_uuid_required(current_user.id),
        family_id=to_uuid_required(current_user.family_id),
    )
    
    required_completed = progress.get("required_completed", 0)
    required_total = progress.get("required_total", 0)
    bonus_completed = progress.get("bonus_completed", 0)
    bonus_total = progress.get("bonus_total", 0)
    
    # Calculate completion percentage (default tasks only)
    completion_pct = int((required_completed / required_total) * 100) if required_total > 0 else 0
    
    # Calculate conversion limit
    conversion_pct, reason = calculate_conversion_limit(
        required_completed,
        required_total,
        bonus_completed,
        bonus_total,
    )
    
    # Calculate max convertible points
    current_points = current_user.points or 0
    max_convertible = int(current_points * (conversion_pct / 100))
    max_amount = round(max_convertible * POINTS_TO_MONEY_RATE, 2)
    
    return ConversionEligibilityResponse(
        eligible=(conversion_pct > 0 and current_points > 0),
        current_points=current_points,
        max_convertible_points=max_convertible,
        max_convertible_amount=max_amount,
        completion_percentage=completion_pct,
        required_completed=required_completed,
        required_total=required_total,
        bonus_completed=bonus_completed,
        bonus_total=bonus_total,
        reason=reason,
    )


@router.post("/convert", response_model=PointConversionResponse)
async def convert_points_to_money(
    request: PointConversionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Convert points to money and deposit into child's Actual Budget accounts.
    
    Validates:
    - User has enough points
    - User meets task completion requirements
    - Requested amount ≤ maximum convertible based on completion
    
    Then:
    1. Deducts points from user balance
    2. Calls Finance API to create deposits (85% checking, 15% savings)
    3. Returns transaction details
    """
    # Only TEEN and CHILD users can convert points
    if current_user.role not in [UserRole.TEEN, UserRole.CHILD]:
        raise HTTPException(
            status_code=403,
            detail="Only children can convert points to money"
        )
    
    # Validate points amount
    if request.points <= 0:
        raise HTTPException(
            status_code=400,
            detail="Points must be greater than 0"
        )
    
    current_points = current_user.points or 0
    
    if request.points > current_points:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient points. You have {current_points} points."
        )
    
    # Get weekly task completion
    progress = await get_week_task_completion(
        db,
        user_id=to_uuid_required(current_user.id),
        family_id=to_uuid_required(current_user.family_id),
    )
    
    required_completed = progress.get("required_completed", 0)
    required_total = progress.get("required_total", 0)
    bonus_completed = progress.get("bonus_completed", 0)
    bonus_total = progress.get("bonus_total", 0)
    
    # Calculate conversion limit
    conversion_pct, reason = calculate_conversion_limit(
        required_completed,
        required_total,
        bonus_completed,
        bonus_total,
    )
    
    if conversion_pct == 0:
        raise HTTPException(
            status_code=403,
            detail=f"Conversion blocked: {reason}"
        )
    
    # Calculate max convertible points
    max_convertible = int(current_points * (conversion_pct / 100))
    
    if request.points > max_convertible:
        raise HTTPException(
            status_code=400,
            detail=f"Can only convert {max_convertible} points ({conversion_pct}% of {current_points}). {reason}"
        )
    
    # Calculate money amount
    total_amount = round(request.points * POINTS_TO_MONEY_RATE, 2)
    checking_amount = round(total_amount * 0.85, 2)
    savings_amount = round(total_amount * 0.15, 2)
    
    # IMPORTANT: Deduct points IMMEDIATELY (Question 6: Answer A)
    # We deduct first to prevent double-conversion if Finance API call fails
    new_balance = current_points - request.points
    
    try:
        # Update user's points balance
        await db.execute(
            update(User)
            .where(User.id == current_user.id)
            .values(points=new_balance)
        )
        await db.commit()
        
        # Refresh user to get updated balance
        await db.refresh(current_user)
        
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to deduct points: {str(e)}"
        )
    
    # Call Finance API to create deposit transactions
    try:
        # Get JWT token from current request context
        # Note: In production, we need to pass the user's JWT token to Finance API
        # For now, we'll make a direct API call
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{FINANCE_API_URL}/api/finance/convert-deposit",
                json={
                    "child_name": current_user.name,
                    "total_amount_mxn": total_amount,
                    "points_converted": request.points,
                    "notes": f"Converted {request.points} points from task completion",
                },
                headers={
                    # Finance API needs family-aware auth - we'll need to pass JWT
                    # For now, this will work if FINANCE_API_KEY is not set (dev mode)
                },
                timeout=30.0,
            )
            
            if response.status_code != 200:
                # ROLLBACK: Points were already deducted, need to refund
                await db.execute(
                    update(User)
                    .where(User.id == current_user.id)
                    .values(points=current_points)  # Restore original balance
                )
                await db.commit()
                
                raise HTTPException(
                    status_code=500,
                    detail=f"Finance API error: {response.text}"
                )
            
            result = response.json()
            
    except httpx.RequestError as e:
        # ROLLBACK: Restore points
        await db.execute(
            update(User)
            .where(User.id == current_user.id)
            .values(points=current_points)
        )
        await db.commit()
        
        raise HTTPException(
            status_code=503,
            detail=f"Could not connect to Finance API: {str(e)}"
        )
    
    # Calculate completion percentage for response
    completion_pct = int((required_completed / required_total) * 100) if required_total > 0 else 0
    
    return PointConversionResponse(
        success=True,
        points_converted=request.points,
        money_amount=total_amount,
        currency=CURRENCY,
        checking_amount=checking_amount,
        savings_amount=savings_amount,
        new_points_balance=new_balance,
        completion_percentage=completion_pct,
        max_convertible_points=max_convertible,
        checking_transaction_id=result["checking_deposit"]["transaction_id"],
        savings_transaction_id=result["savings_deposit"]["transaction_id"],
    )
