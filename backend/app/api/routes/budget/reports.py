"""
Report routes

Analytics and reporting endpoints for budget data.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date
from typing import Optional
from uuid import UUID

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.type_utils import to_uuid_required
from app.core.premium import require_feature
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
    await require_feature("budget_reports", db, current_user)
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
    await require_feature("budget_reports", db, current_user)
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
    await require_feature("budget_reports", db, current_user)
    family_id = to_uuid_required(current_user.family_id)
    
    report = await ReportService.get_net_worth(
        db, family_id, as_of_date
    )

    return report


@router.get("/cash-flow-forecast")
async def get_cash_flow_forecast(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    horizon_days: int = Query(30, ge=1, le=365, description="Days to project forward (e.g. 30, 60, 90)"),
    as_of_date: Optional[date] = Query(None, description="Project from this date (default: today)"),
):
    """Cash-flow forecast + bill calendar for the coming horizon.

    Projects active recurring transactions forward as upcoming/expected items,
    returns a projected running-balance series (current balance + scheduled
    income − scheduled bills) per account and total, plus an ``upcoming`` list
    ready to render as a bill calendar / list-by-date.
    """
    await require_feature("budget_reports", db, current_user)
    family_id = to_uuid_required(current_user.family_id)

    return await ReportService.get_cash_flow_forecast(
        db, family_id, horizon_days=horizon_days, as_of_date=as_of_date
    )
