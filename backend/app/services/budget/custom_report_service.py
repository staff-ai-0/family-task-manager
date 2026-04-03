"""
Custom Report Service

Business logic for saved custom report configurations and execution.
"""

from datetime import date, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import BudgetCustomReport
from app.schemas.budget import CustomReportCreate, CustomReportUpdate
from app.services.base_service import BaseFamilyService
from app.services.budget.report_service import ReportService


class CustomReportService(BaseFamilyService[BudgetCustomReport]):
    """Service for custom report CRUD and data generation."""

    model = BudgetCustomReport

    @classmethod
    async def create(
        cls,
        db: AsyncSession,
        family_id: UUID,
        created_by: UUID,
        data: CustomReportCreate,
    ) -> BudgetCustomReport:
        """Create a new custom report configuration."""
        report = BudgetCustomReport(
            family_id=family_id,
            name=data.name,
            config=data.config,
            created_by=created_by,
        )
        db.add(report)
        await db.commit()
        await db.refresh(report)
        return report

    @classmethod
    async def update(
        cls,
        db: AsyncSession,
        report_id: UUID,
        family_id: UUID,
        data: CustomReportUpdate,
    ) -> BudgetCustomReport:
        """Update a custom report configuration."""
        update_data = data.model_dump(exclude_unset=True)
        return await cls.update_by_id(db, report_id, family_id, update_data)

    @classmethod
    async def generate_data(
        cls,
        db: AsyncSession,
        report: BudgetCustomReport,
        family_id: UUID,
    ) -> dict:
        """Execute a saved report and return its data.

        Reads the report's config and delegates to the appropriate
        ReportService method based on config.group_by.

        Config fields used:
        - group_by: "category" | "group" | "month" | "payee"
        - start_date: ISO date string (optional)
        - end_date: ISO date string (optional)
        - date_range: "last_30" | "last_90" | "last_365" | "this_month" | "this_year" | "custom" (optional)
        - balance_type: "expense" | "income" | "all" (optional, for income_vs_expense)
        """
        config = report.config or {}
        group_by = config.get("group_by", "category")

        # Resolve date range
        start_date, end_date = _resolve_date_range(config)

        # Delegate to appropriate report method
        if group_by in ("category", "group", "month", "payee"):
            return await ReportService.get_spending_report(
                db, family_id, start_date, end_date, group_by=group_by
            )
        elif group_by == "income_vs_expense":
            time_group = config.get("time_group", "month")
            return await ReportService.get_income_vs_expense(
                db, family_id, start_date, end_date, group_by=time_group
            )
        elif group_by == "net_worth":
            return await ReportService.get_net_worth(db, family_id, end_date)
        else:
            # Default to category spending
            return await ReportService.get_spending_report(
                db, family_id, start_date, end_date, group_by="category"
            )


def _resolve_date_range(config: dict) -> tuple[date, date]:
    """Resolve date range from config, returning (start_date, end_date)."""
    today = date.today()
    date_range = config.get("date_range", "last_30")

    if date_range == "custom":
        start_str = config.get("start_date")
        end_str = config.get("end_date")
        start_date = date.fromisoformat(start_str) if start_str else today - timedelta(days=30)
        end_date = date.fromisoformat(end_str) if end_str else today
        return start_date, end_date

    if date_range == "last_30":
        return today - timedelta(days=30), today
    elif date_range == "last_90":
        return today - timedelta(days=90), today
    elif date_range == "last_365":
        return today - timedelta(days=365), today
    elif date_range == "this_month":
        return date(today.year, today.month, 1), today
    elif date_range == "this_year":
        return date(today.year, 1, 1), today
    else:
        return today - timedelta(days=30), today
