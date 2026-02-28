"""
Month budget view routes

Endpoints for comprehensive monthly budget views.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date
from typing import Dict, Any

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.type_utils import to_uuid_required
from app.services.budget.category_service import CategoryGroupService
from app.services.budget.allocation_service import AllocationService
from app.services.budget.transaction_service import TransactionService
from app.models import User

router = APIRouter()


@router.get("/{year}/{month}")
async def get_month_budget(
    year: int,
    month: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Get complete budget view for a specific month.
    
    Returns category groups with categories, each category showing:
    - Budgeted amount
    - Actual spending (activity)
    - Available balance
    """
    family_id = to_uuid_required(current_user.family_id)
    
    # Create month date (first day of month)
    month_date = date(year, month, 1)
    
    # Get all category groups with categories
    groups = await CategoryGroupService.list_with_categories(
        db, family_id, include_hidden=False
    )
    
    # Get allocations for this month
    allocations = await AllocationService.list_by_month(db, family_id, month_date)
    allocation_map = {alloc.category_id: alloc.budgeted_amount for alloc in allocations}
    
    # Build response
    result = {
        "month": month_date.isoformat(),
        "year": year,
        "month_num": month,
        "category_groups": [],
        "totals": {
            "budgeted": 0,
            "activity": 0,
            "available": 0,
        }
    }
    
    for group in groups:
        group_data = {
            "id": str(group.id),
            "name": group.name,
            "is_income": group.is_income,
            "categories": [],
            "total_budgeted": 0,
            "total_activity": 0,
            "total_available": 0,
        }
        
        for category in group.categories:
            # Get budgeted amount for this category
            budgeted = allocation_map.get(category.id, 0)
            
            # Get activity (actual spending) for this month
            activity = await TransactionService.get_category_activity(
                db, category.id, family_id, month_date
            )
            
            # Calculate available
            available = budgeted + activity  # activity is negative for expenses
            
            category_data = {
                "id": str(category.id),
                "name": category.name,
                "budgeted": budgeted,
                "activity": activity,
                "available": available,
                "goal_amount": category.goal_amount,
                "rollover_enabled": category.rollover_enabled,
            }
            
            group_data["categories"].append(category_data)
            group_data["total_budgeted"] += budgeted
            group_data["total_activity"] += activity
            group_data["total_available"] += available
        
        result["category_groups"].append(group_data)
        
        # Add to grand totals
        if not group.is_income:
            result["totals"]["budgeted"] += group_data["total_budgeted"]
            result["totals"]["activity"] += group_data["total_activity"]
            result["totals"]["available"] += group_data["total_available"]
    
    return result


@router.get("/{year}/{month}/summary")
async def get_month_summary(
    year: int,
    month: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Get summary statistics for a month"""
    family_id = to_uuid_required(current_user.family_id)
    month_date = date(year, month, 1)
    
    # Get all allocations for the month
    allocations = await AllocationService.list_by_month(db, family_id, month_date)
    total_budgeted = sum(alloc.budgeted_amount for alloc in allocations)
    
    # For now, return basic stats
    # TODO: Add income tracking, balance calculations, etc.
    return {
        "month": month_date.isoformat(),
        "total_budgeted": total_budgeted,
        "total_income": 0,  # To be implemented
        "total_spent": 0,   # To be calculated from transactions
        "to_budget": 0,      # Income - Budgeted
    }
