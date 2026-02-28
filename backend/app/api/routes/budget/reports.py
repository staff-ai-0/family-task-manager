"""
Report routes

Analytics and reporting endpoints for budget data.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date
from uuid import UUID

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.type_utils import to_uuid_required
from app.services.budget.report_service import ReportService
from app.models import User

router = APIRouter()


@router.get("/spending")
async def get_spending_report(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    start_date: date = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: date = Query(..., description="End date (YYYY-MM-DD)"),
    group_by: str = Query("category", description="Group by: category, group, month, payee"),
):
    """
    Get spending report grouped by category, group, month, or payee.
    
    Returns transaction totals and counts for the specified period.
    """
    family_id = to_uuid_required(current_user.family_id)
    
    report = await ReportService.get_spending_report(
        db, family_id, start_date, end_date, group_by
    )
    
    return report


@router.get("/income-vs-expense")
async def get_income_vs_expense_report(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    start_date: date = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: date = Query(..., description="End date (YYYY-MM-DD)"),
    group_by: str = Query("month", description="Group by: month, week, day"),
):
    """
    Get income vs expense report over time.
    
    Returns income, expense, and net amounts grouped by time period.
    """
    family_id = to_uuid_required(current_user.family_id)
    
    report = await ReportService.get_income_vs_expense(
        db, family_id, start_date, end_date, group_by
    )
    
    return report


@router.get("/net-worth")
async def get_net_worth_report(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    as_of_date: date = Query(None, description="Calculate as of date (default: today)"),
):
    """
    Get net worth report (total assets minus liabilities).
    
    Returns account balances, total assets, total liabilities, and net worth.
    """
    family_id = to_uuid_required(current_user.family_id)
    
    report = await ReportService.get_net_worth(
        db, family_id, as_of_date
    )
    
    return report
