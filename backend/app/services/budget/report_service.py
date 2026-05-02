"""
Report Service

Business logic for budget reports and analytics.
"""

from datetime import date, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, case
from typing import Dict, List
from uuid import UUID

from app.models.budget import (
    BudgetAccount,
    BudgetCategory,
    BudgetCategoryGroup,
    BudgetTransaction,
)


class ReportService:
    """Service for budget reports and analytics"""

    @classmethod
    async def get_spending_report(
        cls,
        db: AsyncSession,
        family_id: UUID,
        start_date: date,
        end_date: date,
        group_by: str = "category",  # category, group, month, payee
    ) -> Dict:
        """
        Generate spending report grouped by category, group, month, or payee.
        
        Args:
            db: Database session
            family_id: Family ID
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            group_by: How to group the data
        
        Returns:
            Dict with spending breakdown
        """
        if group_by == "category":
            return await cls._spending_by_category(db, family_id, start_date, end_date)
        elif group_by == "group":
            return await cls._spending_by_group(db, family_id, start_date, end_date)
        elif group_by == "month":
            return await cls._spending_by_month(db, family_id, start_date, end_date)
        elif group_by == "payee":
            return await cls._spending_by_payee(db, family_id, start_date, end_date)
        else:
            raise ValueError(f"Invalid group_by value: {group_by}")
    
    @classmethod
    async def _spending_by_category(
        cls,
        db: AsyncSession,
        family_id: UUID,
        start_date: date,
        end_date: date,
    ) -> Dict:
        """Get spending grouped by category"""
        from app.models.budget import BudgetPayee
        
        # Query for spending by category
        query = (
            select(
                BudgetCategory.id,
                BudgetCategory.name,
                BudgetCategoryGroup.name.label("group_name"),
                func.sum(BudgetTransaction.amount).label("total"),
                func.count(BudgetTransaction.id).label("transaction_count"),
            )
            .select_from(BudgetTransaction)
            .join(BudgetCategory, BudgetTransaction.category_id == BudgetCategory.id)
            .join(BudgetCategoryGroup, BudgetCategory.group_id == BudgetCategoryGroup.id)
            .where(
                and_(
                    BudgetTransaction.family_id == family_id,
                    BudgetTransaction.date >= start_date,
                    BudgetTransaction.date <= end_date,
                    BudgetTransaction.category_id.isnot(None),
                    BudgetTransaction.deleted_at.is_(None),
                )
            )
            .group_by(BudgetCategory.id, BudgetCategory.name, BudgetCategoryGroup.name)
            .order_by(func.sum(BudgetTransaction.amount).desc())
        )
        
        result = await db.execute(query)
        rows = result.all()
        
        categories = []
        total_amount = 0
        
        for row in rows:
            amount = row.total or 0
            categories.append({
                "category_id": str(row.id),
                "category_name": row.name,
                "group_name": row.group_name,
                "amount": amount,
                "amount_currency": amount / 100,
                "transaction_count": row.transaction_count,
            })
            total_amount += amount
        
        return {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "group_by": "category",
            "categories": categories,
            "total": total_amount,
            "total_currency": total_amount / 100,
        }
    
    @classmethod
    async def _spending_by_group(
        cls,
        db: AsyncSession,
        family_id: UUID,
        start_date: date,
        end_date: date,
    ) -> Dict:
        """Get spending grouped by category group"""
        query = (
            select(
                BudgetCategoryGroup.id,
                BudgetCategoryGroup.name,
                func.sum(BudgetTransaction.amount).label("total"),
                func.count(BudgetTransaction.id).label("transaction_count"),
            )
            .select_from(BudgetTransaction)
            .join(BudgetCategory, BudgetTransaction.category_id == BudgetCategory.id)
            .join(BudgetCategoryGroup, BudgetCategory.group_id == BudgetCategoryGroup.id)
            .where(
                and_(
                    BudgetTransaction.family_id == family_id,
                    BudgetTransaction.date >= start_date,
                    BudgetTransaction.date <= end_date,
                    BudgetTransaction.category_id.isnot(None),
                    BudgetTransaction.deleted_at.is_(None),
                )
            )
            .group_by(BudgetCategoryGroup.id, BudgetCategoryGroup.name)
            .order_by(func.sum(BudgetTransaction.amount).desc())
        )
        
        result = await db.execute(query)
        rows = result.all()
        
        groups = []
        total_amount = 0
        
        for row in rows:
            amount = row.total or 0
            groups.append({
                "group_id": str(row.id),
                "group_name": row.name,
                "amount": amount,
                "amount_currency": amount / 100,
                "transaction_count": row.transaction_count,
            })
            total_amount += amount
        
        return {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "group_by": "group",
            "groups": groups,
            "total": total_amount,
            "total_currency": total_amount / 100,
        }
    
    @classmethod
    async def _spending_by_month(
        cls,
        db: AsyncSession,
        family_id: UUID,
        start_date: date,
        end_date: date,
    ) -> Dict:
        """Get spending grouped by month"""
        # SQLAlchemy query to extract year-month and sum
        query = (
            select(
                func.date_trunc('month', BudgetTransaction.date).label('month'),
                func.sum(BudgetTransaction.amount).label('total'),
                func.count(BudgetTransaction.id).label('transaction_count'),
            )
            .where(
                and_(
                    BudgetTransaction.family_id == family_id,
                    BudgetTransaction.date >= start_date,
                    BudgetTransaction.date <= end_date,
                    BudgetTransaction.deleted_at.is_(None),
                )
            )
            .group_by('month')
            .order_by('month')
        )
        
        result = await db.execute(query)
        rows = result.all()
        
        months = []
        total_amount = 0
        
        for row in rows:
            amount = row.total or 0
            months.append({
                "month": row.month.strftime("%Y-%m") if row.month else None,
                "amount": amount,
                "amount_currency": amount / 100,
                "transaction_count": row.transaction_count,
            })
            total_amount += amount
        
        return {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "group_by": "month",
            "months": months,
            "total": total_amount,
            "total_currency": total_amount / 100,
        }
    
    @classmethod
    async def _spending_by_payee(
        cls,
        db: AsyncSession,
        family_id: UUID,
        start_date: date,
        end_date: date,
    ) -> Dict:
        """Get spending grouped by payee"""
        from app.models.budget import BudgetPayee
        
        query = (
            select(
                BudgetPayee.id,
                BudgetPayee.name,
                func.sum(BudgetTransaction.amount).label("total"),
                func.count(BudgetTransaction.id).label("transaction_count"),
            )
            .select_from(BudgetTransaction)
            .join(BudgetPayee, BudgetTransaction.payee_id == BudgetPayee.id)
            .where(
                and_(
                    BudgetTransaction.family_id == family_id,
                    BudgetTransaction.date >= start_date,
                    BudgetTransaction.date <= end_date,
                    BudgetTransaction.payee_id.isnot(None),
                    BudgetTransaction.deleted_at.is_(None),
                )
            )
            .group_by(BudgetPayee.id, BudgetPayee.name)
            .order_by(func.sum(BudgetTransaction.amount).desc())
        )
        
        result = await db.execute(query)
        rows = result.all()
        
        payees = []
        total_amount = 0
        
        for row in rows:
            amount = row.total or 0
            payees.append({
                "payee_id": str(row.id),
                "payee_name": row.name,
                "amount": amount,
                "amount_currency": amount / 100,
                "transaction_count": row.transaction_count,
            })
            total_amount += amount
        
        return {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "group_by": "payee",
            "payees": payees,
            "total": total_amount,
            "total_currency": total_amount / 100,
        }
    
    @classmethod
    async def get_income_vs_expense(
        cls,
        db: AsyncSession,
        family_id: UUID,
        start_date: date,
        end_date: date,
        group_by: str = "month",  # month, week, day
    ) -> Dict:
        """
        Generate income vs expense report over time.
        
        Args:
            db: Database session
            family_id: Family ID
            start_date: Start date
            end_date: End date
            group_by: Time period grouping (month, week, day)
        
        Returns:
            Dict with income and expense breakdown over time
        """
        # Determine grouping function
        if group_by == "month":
            trunc_func = func.date_trunc('month', BudgetTransaction.date)
        elif group_by == "week":
            trunc_func = func.date_trunc('week', BudgetTransaction.date)
        elif group_by == "day":
            trunc_func = func.date_trunc('day', BudgetTransaction.date)
        else:
            raise ValueError(f"Invalid group_by value: {group_by}")
        
        # Query with income/expense split
        query = (
            select(
                trunc_func.label('period'),
                func.sum(case((BudgetTransaction.amount > 0, BudgetTransaction.amount), else_=0)).label('income'),
                func.sum(case((BudgetTransaction.amount < 0, -BudgetTransaction.amount), else_=0)).label('expense'),
                func.sum(BudgetTransaction.amount).label('net'),
            )
            .where(
                and_(
                    BudgetTransaction.family_id == family_id,
                    BudgetTransaction.date >= start_date,
                    BudgetTransaction.date <= end_date,
                    BudgetTransaction.deleted_at.is_(None),
                )
            )
            .group_by('period')
            .order_by('period')
        )
        
        result = await db.execute(query)
        rows = result.all()
        
        periods = []
        total_income = 0
        total_expense = 0
        
        for row in rows:
            income = row.income or 0
            expense = row.expense or 0
            net = row.net or 0
            
            periods.append({
                "period": row.period.isoformat() if row.period else None,
                "income": income,
                "income_currency": income / 100,
                "expense": expense,
                "expense_currency": expense / 100,
                "net": net,
                "net_currency": net / 100,
            })
            
            total_income += income
            total_expense += expense
        
        return {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "group_by": group_by,
            "periods": periods,
            "totals": {
                "income": total_income,
                "income_currency": total_income / 100,
                "expense": total_expense,
                "expense_currency": total_expense / 100,
                "net": total_income - total_expense,
                "net_currency": (total_income - total_expense) / 100,
            },
        }
    
    @classmethod
    async def get_net_worth(
        cls,
        db: AsyncSession,
        family_id: UUID,
        as_of_date: date = None,
    ) -> Dict:
        """
        Calculate total net worth (all account balances).
        
        Args:
            db: Database session
            family_id: Family ID
            as_of_date: Calculate net worth as of this date (default: today)
        
        Returns:
            Dict with account balances and total net worth
        """
        from app.services.budget.account_service import AccountService
        
        if not as_of_date:
            as_of_date = date.today()
        
        # Get all accounts and their balances
        accounts = await AccountService.list_by_family(db, family_id)
        
        account_balances = []
        assets_total = 0
        liabilities_total = 0
        
        for account in accounts:
            if account.closed:
                continue
            
            balance_info = await AccountService.get_balance(
                db, account.id, family_id, as_of_date
            )
            balance = balance_info["balance"]
            
            # Determine if asset or liability based on account type and balance
            is_liability = account.type in ["credit_card", "loan"] or balance < 0
            
            account_balances.append({
                "account_id": str(account.id),
                "account_name": account.name,
                "account_type": account.type,
                "balance": balance,
                "balance_currency": balance / 100,
                "is_liability": is_liability,
                "offbudget": account.offbudget,
            })
            
            if is_liability:
                liabilities_total += abs(balance)
            else:
                assets_total += balance
        
        net_worth = assets_total - liabilities_total
        
        return {
            "as_of_date": as_of_date.isoformat(),
            "accounts": account_balances,
            "assets": assets_total,
            "assets_currency": assets_total / 100,
            "liabilities": liabilities_total,
            "liabilities_currency": liabilities_total / 100,
            "net_worth": net_worth,
            "net_worth_currency": net_worth / 100,
        }

    @classmethod
    async def get_net_worth_history(
        cls,
        db: AsyncSession,
        family_id: UUID,
        months: int = 12,
    ) -> Dict:
        """Net worth at end of each of the last N months.

        Excludes closed accounts. Returns {series, months, current_net_worth,
        current_net_worth_currency}. Uses a single grouped query plus an
        all-time-prior baseline per account to avoid N*M round-trips.
        """
        from dateutil.relativedelta import relativedelta
        from app.services.budget.account_service import AccountService
        from app.models.budget import BudgetAccount

        accounts = await AccountService.list_by_family(db, family_id)
        open_accounts = [a for a in accounts if not a.closed]

        if not open_accounts:
            return {
                "series": [],
                "months": months,
                "current_net_worth": 0,
                "current_net_worth_currency": 0.0,
            }

        today = date.today()
        current_month = date(today.year, today.month, 1)
        month_starts = [
            current_month - relativedelta(months=i)
            for i in range(months - 1, -1, -1)
        ]
        oldest_month = month_starts[0]

        starting_balance_by_acct = {a.id: a.starting_balance for a in open_accounts}
        open_account_ids = list(starting_balance_by_acct.keys())

        # Prior-period sum (everything strictly before the oldest displayed month)
        prior_q = (
            select(
                BudgetTransaction.account_id,
                func.coalesce(func.sum(BudgetTransaction.amount), 0).label("amt"),
            )
            .where(
                and_(
                    BudgetTransaction.family_id == family_id,
                    BudgetTransaction.account_id.in_(open_account_ids),
                    BudgetTransaction.date < oldest_month,
                    BudgetTransaction.deleted_at.is_(None),
                )
            )
            .group_by(BudgetTransaction.account_id)
        )
        prior_by_acct: dict = {row.account_id: row.amt for row in (await db.execute(prior_q)).all()}

        # Per-month activity per account, single query
        month_col = func.date_trunc("month", BudgetTransaction.date).label("month")
        period_q = (
            select(
                BudgetTransaction.account_id,
                month_col,
                func.coalesce(func.sum(BudgetTransaction.amount), 0).label("amt"),
            )
            .where(
                and_(
                    BudgetTransaction.family_id == family_id,
                    BudgetTransaction.account_id.in_(open_account_ids),
                    BudgetTransaction.date >= oldest_month,
                    BudgetTransaction.date <= (current_month + relativedelta(months=1)) - timedelta(days=1),
                    BudgetTransaction.deleted_at.is_(None),
                )
            )
            .group_by(BudgetTransaction.account_id, month_col)
        )
        activity: dict = {}
        for row in (await db.execute(period_q)).all():
            month_key = row.month.date() if hasattr(row.month, "date") else row.month
            activity[(row.account_id, date(month_key.year, month_key.month, 1))] = row.amt

        running = {
            acct_id: starting_balance_by_acct[acct_id] + prior_by_acct.get(acct_id, 0)
            for acct_id in open_account_ids
        }

        series = []
        for ms in month_starts:
            net_worth = 0
            for acct_id in open_account_ids:
                running[acct_id] += activity.get((acct_id, ms), 0)
                net_worth += running[acct_id]
            series.append({
                "month": ms.strftime("%Y-%m"),
                "net_worth": net_worth,
                "net_worth_currency": net_worth / 100,
            })

        current = series[-1]["net_worth"] if series else 0
        return {
            "series": series,
            "months": months,
            "current_net_worth": current,
            "current_net_worth_currency": current / 100,
        }

    @classmethod
    async def get_budget_vs_actual(
        cls,
        db: AsyncSession,
        family_id: UUID,
        month: date,
    ) -> Dict:
        """Budgeted vs actual spending per category for a month (expense groups only).

        Returns {month, groups: [{group_name, categories: [{category_name, budgeted,
        actual, variance, pct_used}]}], totals: {budgeted, actual, variance}}.
        actual is reported as the absolute value of expense activity.
        pct_used is None when budgeted == 0.
        """
        from app.models.budget import BudgetAllocation
        from dateutil.relativedelta import relativedelta
        end_of_month = (month + relativedelta(months=1)) - timedelta(days=1)

        # Single query: pull all expense groups + visible non-deleted categories
        cat_q = (
            select(BudgetCategoryGroup, BudgetCategory)
            .join(BudgetCategory, BudgetCategory.group_id == BudgetCategoryGroup.id)
            .where(
                and_(
                    BudgetCategoryGroup.family_id == family_id,
                    BudgetCategoryGroup.is_income == False,
                    BudgetCategoryGroup.deleted_at.is_(None),
                    BudgetCategory.deleted_at.is_(None),
                    BudgetCategory.hidden == False,
                )
            )
            .order_by(
                BudgetCategoryGroup.sort_order, BudgetCategoryGroup.name,
                BudgetCategory.sort_order, BudgetCategory.name,
            )
        )
        rows = (await db.execute(cat_q)).all()
        if not rows:
            return {
                "month": month.isoformat(),
                "groups": [],
                "totals": {"budgeted": 0, "actual": 0, "variance": 0},
            }

        category_ids = [cat.id for _, cat in rows]

        # Allocations for the target month, all categories at once
        alloc_q = (
            select(BudgetAllocation.category_id, BudgetAllocation.budgeted_amount)
            .where(
                and_(
                    BudgetAllocation.family_id == family_id,
                    BudgetAllocation.month == month,
                    BudgetAllocation.category_id.in_(category_ids),
                )
            )
        )
        budgeted_by_cat = {cid: amt for cid, amt in (await db.execute(alloc_q)).all()}

        # Activity sum per category over month, single query
        act_q = (
            select(
                BudgetTransaction.category_id,
                func.coalesce(func.sum(BudgetTransaction.amount), 0).label("amt"),
            )
            .where(
                and_(
                    BudgetTransaction.family_id == family_id,
                    BudgetTransaction.category_id.in_(category_ids),
                    BudgetTransaction.date >= month,
                    BudgetTransaction.date <= end_of_month,
                    BudgetTransaction.deleted_at.is_(None),
                )
            )
            .group_by(BudgetTransaction.category_id)
        )
        activity_by_cat = {row.category_id: row.amt for row in (await db.execute(act_q)).all()}

        result_groups: list = []
        current_group_id = None
        current_entry: dict = {}
        total_budgeted = 0
        total_actual = 0

        for grp, cat in rows:
            budgeted = budgeted_by_cat.get(cat.id, 0)
            actual = abs(activity_by_cat.get(cat.id, 0))
            variance = budgeted - actual
            pct_used = None if budgeted == 0 else round(actual / budgeted * 100, 2)

            if grp.id != current_group_id:
                current_entry = {
                    "group_id": str(grp.id),
                    "group_name": grp.name,
                    "categories": [],
                }
                result_groups.append(current_entry)
                current_group_id = grp.id

            current_entry["categories"].append({
                "category_id": str(cat.id),
                "category_name": cat.name,
                "budgeted": budgeted,
                "actual": actual,
                "variance": variance,
                "pct_used": pct_used,
            })
            total_budgeted += budgeted
            total_actual += actual

        return {
            "month": month.isoformat(),
            "groups": result_groups,
            "totals": {
                "budgeted": total_budgeted,
                "actual": total_actual,
                "variance": total_budgeted - total_actual,
            },
        }
