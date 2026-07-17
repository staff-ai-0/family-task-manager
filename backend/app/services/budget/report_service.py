"""
Report Service

Business logic for budget reports and analytics.
"""

from datetime import date, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, case, or_
from typing import Dict, List, Optional
from uuid import UUID

from app.core.time_utils import utc_today
from app.models.budget import (
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
                    BudgetCategoryGroup.is_transfer.is_(False),
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
            amount = int(row.total or 0)
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
                    BudgetCategoryGroup.is_transfer.is_(False),
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
            amount = int(row.total or 0)
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
            .select_from(BudgetTransaction)
            .outerjoin(BudgetCategory, BudgetTransaction.category_id == BudgetCategory.id)
            .outerjoin(BudgetCategoryGroup, BudgetCategory.group_id == BudgetCategoryGroup.id)
            .where(
                and_(
                    BudgetTransaction.family_id == family_id,
                    BudgetTransaction.date >= start_date,
                    BudgetTransaction.date <= end_date,
                    BudgetTransaction.deleted_at.is_(None),
                    or_(
                        BudgetCategoryGroup.is_transfer.is_(False),
                        BudgetCategoryGroup.is_transfer.is_(None),
                    ),
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
            amount = int(row.total or 0)
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
            .outerjoin(BudgetCategory, BudgetTransaction.category_id == BudgetCategory.id)
            .outerjoin(BudgetCategoryGroup, BudgetCategory.group_id == BudgetCategoryGroup.id)
            .where(
                and_(
                    BudgetTransaction.family_id == family_id,
                    BudgetTransaction.date >= start_date,
                    BudgetTransaction.date <= end_date,
                    BudgetTransaction.payee_id.isnot(None),
                    BudgetTransaction.deleted_at.is_(None),
                    or_(
                        BudgetCategoryGroup.is_transfer.is_(False),
                        BudgetCategoryGroup.is_transfer.is_(None),
                    ),
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
            amount = int(row.total or 0)
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
            .select_from(BudgetTransaction)
            .outerjoin(BudgetCategory, BudgetTransaction.category_id == BudgetCategory.id)
            .outerjoin(BudgetCategoryGroup, BudgetCategory.group_id == BudgetCategoryGroup.id)
            .where(
                and_(
                    BudgetTransaction.family_id == family_id,
                    BudgetTransaction.date >= start_date,
                    BudgetTransaction.date <= end_date,
                    BudgetTransaction.deleted_at.is_(None),
                    or_(
                        BudgetCategoryGroup.is_transfer.is_(False),
                        BudgetCategoryGroup.is_transfer.is_(None),
                    ),
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
            income = int(row.income or 0)
            expense = int(row.expense or 0)
            net = int(row.net or 0)
            
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
            as_of_date = utc_today()
        
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
            balance = int(balance_info["balance"])

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

        Includes closed accounts: a closed account that held a balance during
        the window must still contribute to historical net worth, otherwise
        the chart spikes/drops on close events. Soft-deleted accounts are
        excluded via list_by_family. Returns {series, months,
        current_net_worth, current_net_worth_currency}. Uses a single grouped
        query plus an all-time-prior baseline per account to avoid N*M
        round-trips.
        """
        from dateutil.relativedelta import relativedelta
        from app.services.budget.account_service import AccountService

        accounts = await AccountService.list_by_family(db, family_id)

        if not accounts:
            return {
                "series": [],
                "months": months,
                "current_net_worth": 0,
                "current_net_worth_currency": 0.0,
            }

        today = utc_today()
        current_month = date(today.year, today.month, 1)
        month_starts = [
            current_month - relativedelta(months=i)
            for i in range(months - 1, -1, -1)
        ]
        oldest_month = month_starts[0]

        # NOTE: account.starting_balance is also materialized as a synthetic
        # "Starting Balance" BudgetTransaction at account create time (see
        # AccountService.create). Including a.starting_balance here would
        # double-count. Initialize running balances to 0 — the synthetic txn
        # is picked up by either the prior-period sum or the per-month query
        # depending on its date relative to the window.
        account_ids = [a.id for a in accounts]

        # Prior-period sum (everything strictly before the oldest displayed month)
        prior_q = (
            select(
                BudgetTransaction.account_id,
                func.coalesce(func.sum(BudgetTransaction.amount), 0).label("amt"),
            )
            .where(
                and_(
                    BudgetTransaction.family_id == family_id,
                    BudgetTransaction.account_id.in_(account_ids),
                    BudgetTransaction.date < oldest_month,
                    BudgetTransaction.deleted_at.is_(None),
                )
            )
            .group_by(BudgetTransaction.account_id)
        )
        prior_by_acct: dict = {row.account_id: int(row.amt or 0) for row in (await db.execute(prior_q)).all()}

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
                    BudgetTransaction.account_id.in_(account_ids),
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
            activity[(row.account_id, date(month_key.year, month_key.month, 1))] = int(row.amt or 0)

        running = {
            acct_id: prior_by_acct.get(acct_id, 0)
            for acct_id in account_ids
        }

        series = []
        for ms in month_starts:
            net_worth = 0
            for acct_id in account_ids:
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
                    BudgetCategoryGroup.is_transfer == False,
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
        activity_by_cat = {row.category_id: int(row.amt or 0) for row in (await db.execute(act_q)).all()}

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

    # ------------------------------------------------------------------
    # Cash-flow forecast + bill calendar
    # ------------------------------------------------------------------

    @classmethod
    def _project_occurrences(
        cls,
        template,
        window_start: date,
        window_end: date,
        max_occurrences: int = 400,
    ) -> List[date]:
        """Project a recurring template's occurrence dates within a window.

        Iterates on the RAW (weekend-unadjusted) occurrence sequence for a
        strictly-monotonic cursor — feeding a weekend-adjusted date back into
        the calculator can stall (e.g. a daily 'before' rule that keeps
        snapping Saturday back to Friday). Each raw hit is then weekend-adjusted
        for its displayed date. Occurrences already posted (on/before
        ``last_generated_date``) are skipped so they aren't double-counted
        against the current balance. ``after_n`` templates are capped at their
        remaining occurrence budget.
        """
        from app.services.budget.recurring_transaction_service import (
            RecurringTransactionService as _RTS,
        )

        # Never project occurrences the template has already posted.
        lower_bound = window_start
        if template.last_generated_date is not None:
            gen_next = template.last_generated_date + timedelta(days=1)
            if gen_next > lower_bound:
                lower_bound = gen_next

        # Respect after_n: only project the remaining occurrence budget.
        remaining: Optional[int] = None
        if template.end_mode == "after_n" and template.occurrence_limit is not None:
            remaining = max(0, template.occurrence_limit - template.occurrence_count)
            if remaining == 0:
                return []

        def _next_raw(from_d: date) -> Optional[date]:
            return _RTS._calculate_next_occurrence(
                template.start_date,
                template.recurrence_type,
                template.recurrence_interval,
                template.recurrence_pattern,
                template.end_date,
                from_date=from_d,
                end_mode="never",  # limit enforced here, not inside the calc
                weekend_behavior="none",
            )

        # First raw occurrence on/after lower_bound.
        cursor = _next_raw(lower_bound - timedelta(days=1))

        occurrences: List[date] = []
        iterations = 0
        while (
            cursor is not None
            and cursor <= window_end
            and iterations < max_occurrences
        ):
            if cursor >= lower_bound:
                occurrences.append(
                    _RTS._adjust_weekend(cursor, template.weekend_behavior)
                )
                if remaining is not None and len(occurrences) >= remaining:
                    break
            nxt = _next_raw(cursor)
            if nxt is None or nxt <= cursor:
                break
            cursor = nxt
            iterations += 1

        return occurrences

    @classmethod
    async def get_cash_flow_forecast(
        cls,
        db: AsyncSession,
        family_id: UUID,
        horizon_days: int = 30,
        as_of_date: Optional[date] = None,
    ) -> Dict:
        """Project on-budget cash forward over the next ``horizon_days``.

        Builds three things from the family's active recurring templates:
        1. An ``upcoming`` bill/income calendar — every projected occurrence in
           the horizon, sorted by date, ready to render as a list-by-date.
        2. A projected running-balance ``series`` (total across accounts):
           current balance, then each occurrence applied in date order.
        3. Per-account and total summaries: starting balance + scheduled income
           − scheduled bills = projected balance.

        Only on-budget, non-closed accounts (real spendable cash) are included,
        and only templates whose account is in that set are projected. All cents
        values are ints so a Decimal never serializes as a JSON string.
        Family-scoped throughout.
        """
        from app.services.budget.account_service import AccountService
        from app.services.budget.recurring_transaction_service import (
            RecurringTransactionService,
        )

        if as_of_date is None:
            as_of_date = utc_today()
        # Clamp to a sane range so a bad query param can't cost unbounded work.
        horizon_days = max(1, min(int(horizon_days), 365))
        window_start = as_of_date
        window_end = as_of_date + timedelta(days=horizon_days)

        accounts = await AccountService.list_budget_accounts(
            db, family_id, include_closed=False
        )

        if not accounts:
            return {
                "as_of_date": as_of_date.isoformat(),
                "horizon_days": horizon_days,
                "start_date": window_start.isoformat(),
                "end_date": window_end.isoformat(),
                "currency": "MXN",
                "starting_balance": 0,
                "scheduled_income": 0,
                "scheduled_expense": 0,
                "projected_balance": 0,
                "projected_low": 0,
                "accounts": [],
                "upcoming": [],
                "series": [
                    {"date": window_start.isoformat(), "balance": 0},
                    {"date": window_end.isoformat(), "balance": 0},
                ],
            }

        currency = accounts[0].currency or "MXN"
        account_ids = [a.id for a in accounts]
        account_by_id = {a.id: a for a in accounts}

        balances = await AccountService.get_balances_for_accounts(
            db, account_ids, family_id, as_of_date
        )

        # Per-account running tallies keyed by account id.
        acct_start = {aid: int(balances.get(aid, {}).get("balance", 0)) for aid in account_ids}
        acct_income = {aid: 0 for aid in account_ids}
        acct_expense = {aid: 0 for aid in account_ids}

        templates = await RecurringTransactionService.list_by_family_filtered(
            db, family_id, active_only=True
        )
        templates = [t for t in templates if t.account_id in account_by_id]

        # Batch-resolve payee + category display names (avoid lazy-load / N+1).
        payee_ids = {t.payee_id for t in templates if t.payee_id}
        category_ids = {t.category_id for t in templates if t.category_id}
        payee_names: Dict[UUID, str] = {}
        category_names: Dict[UUID, str] = {}
        if payee_ids:
            from app.models.budget import BudgetPayee
            rows = (
                await db.execute(
                    select(BudgetPayee.id, BudgetPayee.name).where(
                        and_(
                            BudgetPayee.family_id == family_id,
                            BudgetPayee.id.in_(payee_ids),
                        )
                    )
                )
            ).all()
            payee_names = {r[0]: r[1] for r in rows}
        if category_ids:
            rows = (
                await db.execute(
                    select(BudgetCategory.id, BudgetCategory.name).where(
                        and_(
                            BudgetCategory.family_id == family_id,
                            BudgetCategory.id.in_(category_ids),
                        )
                    )
                )
            ).all()
            category_names = {r[0]: r[1] for r in rows}

        upcoming: List[Dict] = []
        for template in templates:
            for occ_date in cls._project_occurrences(template, window_start, window_end):
                amount = int(template.amount)
                acct = account_by_id[template.account_id]
                if amount >= 0:
                    acct_income[template.account_id] += amount
                else:
                    acct_expense[template.account_id] += -amount
                upcoming.append({
                    "date": occ_date.isoformat(),
                    "recurring_id": str(template.id),
                    "name": template.name,
                    "amount": amount,
                    "amount_currency": amount / 100,
                    "is_income": amount >= 0,
                    "account_id": str(template.account_id),
                    "account_name": acct.name,
                    "category_id": str(template.category_id) if template.category_id else None,
                    "category_name": category_names.get(template.category_id),
                    "payee_id": str(template.payee_id) if template.payee_id else None,
                    "payee_name": payee_names.get(template.payee_id),
                })

        # Stable ordering: by date, income before expense on the same day, then name.
        upcoming.sort(key=lambda i: (i["date"], 0 if i["is_income"] else 1, i["name"]))

        # Per-account summary rows.
        account_rows: List[Dict] = []
        for aid in account_ids:
            acct = account_by_id[aid]
            start = acct_start[aid]
            income = acct_income[aid]
            expense = acct_expense[aid]
            projected = start + income - expense
            account_rows.append({
                "account_id": str(aid),
                "account_name": acct.name,
                "account_type": acct.type,
                "starting_balance": start,
                "starting_balance_currency": start / 100,
                "scheduled_income": income,
                "scheduled_expense": expense,
                "projected_balance": projected,
                "projected_balance_currency": projected / 100,
            })

        starting_total = sum(acct_start.values())
        income_total = sum(acct_income.values())
        expense_total = sum(acct_expense.values())
        projected_total = starting_total + income_total - expense_total

        # Total projected running-balance series: one point per active date,
        # each holding the end-of-day balance. Endpoints anchor the horizon.
        running = starting_total
        series: List[Dict] = [{
            "date": window_start.isoformat(),
            "balance": running,
            "balance_currency": running / 100,
        }]
        projected_low = starting_total
        for item in upcoming:
            running += item["amount"]
            projected_low = min(projected_low, running)
            if series and series[-1]["date"] == item["date"]:
                series[-1]["balance"] = running
                series[-1]["balance_currency"] = running / 100
            else:
                series.append({
                    "date": item["date"],
                    "balance": running,
                    "balance_currency": running / 100,
                })
        end_iso = window_end.isoformat()
        if series[-1]["date"] != end_iso:
            series.append({
                "date": end_iso,
                "balance": running,
                "balance_currency": running / 100,
            })

        return {
            "as_of_date": as_of_date.isoformat(),
            "horizon_days": horizon_days,
            "start_date": window_start.isoformat(),
            "end_date": window_end.isoformat(),
            "currency": currency,
            "starting_balance": starting_total,
            "starting_balance_currency": starting_total / 100,
            "scheduled_income": income_total,
            "scheduled_income_currency": income_total / 100,
            "scheduled_expense": expense_total,
            "scheduled_expense_currency": expense_total / 100,
            "projected_balance": projected_total,
            "projected_balance_currency": projected_total / 100,
            "projected_low": projected_low,
            "projected_low_currency": projected_low / 100,
            "accounts": account_rows,
            "upcoming": upcoming,
            "series": series,
        }
