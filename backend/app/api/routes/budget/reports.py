"""
Report routes

Analytics and reporting endpoints for budget data.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date
from typing import Optional

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


@router.get("/budget-vs-actual")
async def get_budget_vs_actual(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
):
    """Budget vs Actual per category for one month (parity with Actual's
    spending-vs-budget analysis).

    Returns {month, categories:[{category_id, category_name, group_name,
    budgeted, actual, diff}], totals:{budgeted, actual, diff}} — cents;
    actual is negative for spending; diff = budgeted + actual (positive =
    under budget). Income and transfer groups are excluded.
    """
    from datetime import date as date_type

    from sqlalchemy import and_, func as sa_func, select

    from app.models.budget import (
        BudgetAllocation,
        BudgetCategory,
        BudgetCategoryGroup,
        BudgetTransaction,
    )

    await require_feature("budget_reports", db, current_user)
    family_id = to_uuid_required(current_user.family_id)
    month_start = date_type(year, month, 1)
    month_end = (
        date_type(year + 1, 1, 1) if month == 12
        else date_type(year, month + 1, 1)
    )

    rows = (await db.execute(
        select(
            BudgetCategory.id,
            BudgetCategory.name,
            BudgetCategoryGroup.name.label("group_name"),
            sa_func.coalesce(
                select(sa_func.sum(BudgetAllocation.budgeted_amount))
                .where(
                    BudgetAllocation.category_id == BudgetCategory.id,
                    BudgetAllocation.month == month_start,
                ).scalar_subquery(), 0,
            ).label("budgeted"),
            sa_func.coalesce(
                select(sa_func.sum(BudgetTransaction.amount))
                .where(
                    BudgetTransaction.category_id == BudgetCategory.id,
                    BudgetTransaction.date >= month_start,
                    BudgetTransaction.date < month_end,
                    BudgetTransaction.deleted_at.is_(None),
                ).scalar_subquery(), 0,
            ).label("actual"),
        )
        .join(BudgetCategoryGroup, BudgetCategory.group_id == BudgetCategoryGroup.id)
        .where(
            and_(
                BudgetCategory.family_id == family_id,
                BudgetCategory.deleted_at.is_(None),
                BudgetCategory.hidden.is_(False),
                BudgetCategoryGroup.is_income.is_(False),
                BudgetCategoryGroup.is_transfer.is_(False),
                BudgetCategoryGroup.deleted_at.is_(None),
            )
        )
        .order_by(BudgetCategoryGroup.sort_order, BudgetCategory.sort_order)
    )).all()

    categories = [
        {
            "category_id": str(cid),
            "category_name": cname,
            "group_name": gname,
            "budgeted": int(budgeted),
            "actual": int(actual),
            "diff": int(budgeted) + int(actual),
        }
        for cid, cname, gname, budgeted, actual in rows
    ]
    tot_b = sum(c["budgeted"] for c in categories)
    tot_a = sum(c["actual"] for c in categories)
    return {
        "month": str(month_start),
        "categories": categories,
        "totals": {"budgeted": tot_b, "actual": tot_a, "diff": tot_b + tot_a},
    }


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
