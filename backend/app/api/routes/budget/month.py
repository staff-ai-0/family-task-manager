"""
Month budget view routes

Endpoints for comprehensive monthly budget views.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date, timedelta
from typing import Dict, Any

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.type_utils import to_uuid_required
from app.services.budget.category_service import CategoryGroupService
from app.services.budget.allocation_service import AllocationService
from app.services.budget.account_service import AccountService
from app.models import User
from app.models.budget import BudgetAccount, BudgetTransaction
from sqlalchemy import select, and_, func

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
    
    result = {
        "month": month_date.isoformat(),
        "year": year,
        "month_num": month,
        "category_groups": [],
        "ready_to_assign": 0,
        "totals": {
            "budgeted": 0,
            "activity": 0,
            "available": 0,
            "income": 0,
        }
    }
    
    # Compute end-of-month date for balance snapshot
    if month_date.month == 12:
        end_of_month = date(month_date.year + 1, 1, 1) - timedelta(days=1)
    else:
        end_of_month = date(month_date.year, month_date.month + 1, 1) - timedelta(days=1)

    # Envelope budgeting formula (Actual Budget style):
    #   ready_to_assign = total_on_budget_balance
    #                     - expense_budgeted_this_month
    #                     - (prior_expense_budgeted + prior_expense_activity)
    #
    # prior_expense_budgeted + prior_expense_activity = net leftover already "used" from the pool
    total_on_budget_balance = await AccountService.get_total_on_budget_balance(
        db, family_id, end_of_month
    )
    expense_budgeted_this_month = await AllocationService.get_total_expense_budgeted_for_month(
        db, family_id, month_date
    )
    prior_expense_budgeted = await AllocationService.get_total_expense_budgeted_before_month(
        db, family_id, month_date
    )
    prior_expense_activity = await AllocationService.get_total_expense_activity_before_month(
        db, family_id, month_date
    )
    prior_net = prior_expense_budgeted + prior_expense_activity

    result["ready_to_assign"] = total_on_budget_balance - expense_budgeted_this_month - prior_net

    # Total income this month = all positive transactions in on-budget accounts for this month.
    # This includes uncategorized income (category_id=NULL) like payroll deposits.
    # Income-category activity is a subset of this; we use the raw account-level figure
    # so the summary cards always reflect real money received, not just categorized income.
    income_query = (
        select(func.coalesce(func.sum(BudgetTransaction.amount), 0))
        .where(
            and_(
                BudgetTransaction.family_id == family_id,
                BudgetTransaction.amount > 0,
                BudgetTransaction.date >= month_date,
                BudgetTransaction.date <= end_of_month,
                BudgetTransaction.account_id.in_(
                    select(BudgetAccount.id).where(
                        and_(
                            BudgetAccount.family_id == family_id,
                            BudgetAccount.offbudget == False,
                            BudgetAccount.closed == False,
                        )
                    )
                ),
            )
        )
    )
    income_result = await db.execute(income_query)
    result["totals"]["income"] = income_result.scalar() or 0

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
            summary = await AllocationService.get_category_available_amount(
                db, family_id, category.id, month_date
            )

            category_data = {
                "id": str(category.id),
                "name": category.name,
                "budgeted": summary["budgeted"],
                "activity": summary["activity"],
                "available": summary["available"],
                "previous_balance": summary["previous_balance"],
                "goal_amount": category.goal_amount,
                "rollover_enabled": summary["rollover_enabled"],
            }
            
            group_data["categories"].append(category_data)
            group_data["total_budgeted"] += category_data["budgeted"]
            group_data["total_activity"] += category_data["activity"]
            group_data["total_available"] += category_data["available"]
        
        result["category_groups"].append(group_data)
        
        # Track income for totals reporting
        if group.is_income:
            result["totals"]["income"] += group_data["total_activity"]
        else:
            # Add to grand totals
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
