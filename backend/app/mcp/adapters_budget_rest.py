"""
MCP ServiceAdapter subclasses for remaining budget entities:
category_group, category, payee, transaction, allocation,
goal, rule, recurring, tag, saved_filter, custom_report, receipt_draft.

Each adapter binds to the real app service class using the ACTUAL method
signatures found in the service source. Family scope comes from McpContext —
never from adapter arguments.
"""
from __future__ import annotations

from datetime import date as _date
from uuid import UUID

from app.mcp.adapters import ServiceAdapter
from app.mcp.context import McpContext


# ── helpers ────────────────────────────────────────────────────────────────

def _parse_date(v: str | _date) -> _date:
    """Accept either an ISO string or an existing date object."""
    if isinstance(v, _date):
        return v
    return _date.fromisoformat(v)


# ── category_group ─────────────────────────────────────────────────────────

class CategoryGroupAdapter(ServiceAdapter):
    """Wraps CategoryGroupService (BaseFamilyService[BudgetCategoryGroup])."""

    async def list(self, ctx: McpContext) -> list[dict]:
        from app.services.budget.category_service import CategoryGroupService
        rows = await CategoryGroupService.list_by_family(ctx.db, ctx.family_id)
        return [_ser_group(r) for r in rows]

    async def get(self, ctx: McpContext, entity_id: UUID) -> dict:
        from app.services.budget.category_service import CategoryGroupService
        return _ser_group(await CategoryGroupService.get_by_id(ctx.db, entity_id, ctx.family_id))

    async def create(self, ctx: McpContext, data: dict) -> dict:
        from app.services.budget.category_service import CategoryGroupService
        from app.schemas.budget import CategoryGroupCreate
        r = await CategoryGroupService.create(ctx.db, ctx.family_id, CategoryGroupCreate(**data))
        return _ser_group(r)

    async def update(self, ctx: McpContext, entity_id: UUID, data: dict) -> dict:
        from app.services.budget.category_service import CategoryGroupService
        from app.schemas.budget import CategoryGroupUpdate
        r = await CategoryGroupService.update(ctx.db, entity_id, ctx.family_id, CategoryGroupUpdate(**data))
        return _ser_group(r)

    async def delete(self, ctx: McpContext, entity_id: UUID) -> None:
        from app.services.budget.category_service import CategoryGroupService
        await CategoryGroupService.delete_by_id(ctx.db, entity_id, ctx.family_id)


def _ser_group(g) -> dict:
    return {"id": str(g.id), "name": g.name, "sort_order": g.sort_order,
            "is_income": g.is_income, "hidden": g.hidden}


# ── category ───────────────────────────────────────────────────────────────

class CategoryAdapter(ServiceAdapter):
    """Wraps CategoryService (BaseFamilyService[BudgetCategory])."""

    async def list(self, ctx: McpContext) -> list[dict]:
        from app.services.budget.category_service import CategoryService
        rows = await CategoryService.list_for_family(ctx.db, ctx.family_id, include_hidden=True)
        return [_ser_cat(r) for r in rows]

    async def get(self, ctx: McpContext, entity_id: UUID) -> dict:
        from app.services.budget.category_service import CategoryService
        return _ser_cat(await CategoryService.get_by_id(ctx.db, entity_id, ctx.family_id))

    async def create(self, ctx: McpContext, data: dict) -> dict:
        from app.services.budget.category_service import CategoryService
        from app.schemas.budget import CategoryCreate
        payload = dict(data)
        if "group_id" in payload and isinstance(payload["group_id"], str):
            payload["group_id"] = UUID(payload["group_id"])
        r = await CategoryService.create(ctx.db, ctx.family_id, CategoryCreate(**payload))
        return _ser_cat(r)

    async def update(self, ctx: McpContext, entity_id: UUID, data: dict) -> dict:
        from app.services.budget.category_service import CategoryService
        from app.schemas.budget import CategoryUpdate
        payload = dict(data)
        if "group_id" in payload and isinstance(payload["group_id"], str):
            payload["group_id"] = UUID(payload["group_id"])
        r = await CategoryService.update(ctx.db, entity_id, ctx.family_id, CategoryUpdate(**payload))
        return _ser_cat(r)

    async def delete(self, ctx: McpContext, entity_id: UUID) -> None:
        from app.services.budget.category_service import CategoryService
        # delete_with_reassign supports reassignment; for MCP we just delete (no reassign)
        await CategoryService.delete_with_reassign(ctx.db, entity_id, ctx.family_id)


def _ser_cat(c) -> dict:
    return {
        "id": str(c.id),
        "name": c.name,
        "group_id": str(c.group_id) if c.group_id else None,
        "hidden": c.hidden,
        "goal_amount": c.goal_amount,
    }


# ── payee ──────────────────────────────────────────────────────────────────

class PayeeAdapter(ServiceAdapter):
    """Wraps PayeeService (BaseFamilyService[BudgetPayee])."""

    async def list(self, ctx: McpContext) -> list[dict]:
        from app.services.budget.payee_service import PayeeService
        rows = await PayeeService.list_by_family(ctx.db, ctx.family_id)
        return [_ser_payee(r) for r in rows]

    async def get(self, ctx: McpContext, entity_id: UUID) -> dict:
        from app.services.budget.payee_service import PayeeService
        return _ser_payee(await PayeeService.get_by_id(ctx.db, entity_id, ctx.family_id))

    async def create(self, ctx: McpContext, data: dict) -> dict:
        from app.services.budget.payee_service import PayeeService
        from app.schemas.budget import PayeeCreate
        r = await PayeeService.create(ctx.db, ctx.family_id, PayeeCreate(**data))
        return _ser_payee(r)

    async def update(self, ctx: McpContext, entity_id: UUID, data: dict) -> dict:
        from app.services.budget.payee_service import PayeeService
        from app.schemas.budget import PayeeUpdate
        r = await PayeeService.update(ctx.db, entity_id, ctx.family_id, PayeeUpdate(**data))
        return _ser_payee(r)

    async def delete(self, ctx: McpContext, entity_id: UUID) -> None:
        from app.services.budget.payee_service import PayeeService
        await PayeeService.delete_by_id(ctx.db, entity_id, ctx.family_id)


def _ser_payee(p) -> dict:
    return {
        "id": str(p.id),
        "name": p.name,
        "notes": p.notes,
        "is_favorite": p.is_favorite,
    }


# ── transaction ────────────────────────────────────────────────────────────

class TransactionAdapter(ServiceAdapter):
    """Wraps TransactionService (BaseFamilyService[BudgetTransaction]).

    create/update are money-moving ops → both are in destructive_ops in the
    EntitySpec; the MCP dispatch gate handles the HITL confirmation.
    """

    async def list(self, ctx: McpContext) -> list[dict]:
        from app.services.budget.transaction_service import TransactionService
        rows = await TransactionService.list_by_family(ctx.db, ctx.family_id, limit=200)
        return [_ser_txn(r) for r in rows]

    async def get(self, ctx: McpContext, entity_id: UUID) -> dict:
        from app.services.budget.transaction_service import TransactionService
        return _ser_txn(await TransactionService.get_by_id(ctx.db, entity_id, ctx.family_id))

    async def create(self, ctx: McpContext, data: dict) -> dict:
        from app.services.budget.transaction_service import TransactionService
        from app.schemas.budget import TransactionCreate
        payload = dict(data)
        if "date" in payload and isinstance(payload["date"], str):
            payload["date"] = _parse_date(payload["date"])
        r = await TransactionService.create(
            ctx.db, ctx.family_id, TransactionCreate(**payload), user_id=ctx.user_id
        )
        return _ser_txn(r)

    async def update(self, ctx: McpContext, entity_id: UUID, data: dict) -> dict:
        from app.services.budget.transaction_service import TransactionService
        from app.schemas.budget import TransactionUpdate
        payload = dict(data)
        if "date" in payload and isinstance(payload["date"], str):
            payload["date"] = _parse_date(payload["date"])
        r = await TransactionService.update(
            ctx.db, entity_id, ctx.family_id, TransactionUpdate(**payload)
        )
        return _ser_txn(r)

    async def delete(self, ctx: McpContext, entity_id: UUID) -> None:
        from app.services.budget.transaction_service import TransactionService
        await TransactionService.delete_by_id(ctx.db, entity_id, ctx.family_id)


def _ser_txn(t) -> dict:
    return {
        "id": str(t.id),
        "account_id": str(t.account_id),
        "date": str(t.date),
        "amount": t.amount,
        "payee_id": str(t.payee_id) if t.payee_id else None,
        "category_id": str(t.category_id) if t.category_id else None,
        "notes": t.notes,
        "cleared": t.cleared,
    }


# ── allocation ─────────────────────────────────────────────────────────────

class AllocationAdapter(ServiceAdapter):
    """Wraps AllocationService (BaseFamilyService[BudgetAllocation])."""

    async def list(self, ctx: McpContext) -> list[dict]:
        from app.services.budget.allocation_service import AllocationService
        rows = await AllocationService.list_by_family(ctx.db, ctx.family_id, limit=500)
        return [_ser_alloc(r) for r in rows]

    async def get(self, ctx: McpContext, entity_id: UUID) -> dict:
        from app.services.budget.allocation_service import AllocationService
        return _ser_alloc(await AllocationService.get_by_id(ctx.db, entity_id, ctx.family_id))

    async def create(self, ctx: McpContext, data: dict) -> dict:
        from app.services.budget.allocation_service import AllocationService
        from app.schemas.budget import AllocationCreate
        payload = dict(data)
        if "month" in payload and isinstance(payload["month"], str):
            payload["month"] = _parse_date(payload["month"])
        r = await AllocationService.create(ctx.db, ctx.family_id, AllocationCreate(**payload))
        return _ser_alloc(r)

    async def update(self, ctx: McpContext, entity_id: UUID, data: dict) -> dict:
        from app.services.budget.allocation_service import AllocationService
        from app.schemas.budget import AllocationUpdate
        r = await AllocationService.update(
            ctx.db, entity_id, ctx.family_id, AllocationUpdate(**data)
        )
        return _ser_alloc(r)

    async def delete(self, ctx: McpContext, entity_id: UUID) -> None:
        from app.services.budget.allocation_service import AllocationService
        await AllocationService.delete_by_id(ctx.db, entity_id, ctx.family_id)


def _ser_alloc(a) -> dict:
    return {
        "id": str(a.id),
        "category_id": str(a.category_id),
        "month": str(a.month),
        "budgeted_amount": a.budgeted_amount,
        "notes": a.notes,
    }


# ── goal ───────────────────────────────────────────────────────────────────

class GoalAdapter(ServiceAdapter):
    """Wraps GoalService (BaseFamilyService[BudgetGoal])."""

    async def list(self, ctx: McpContext) -> list[dict]:
        from app.services.budget.goal_service import GoalService
        rows = await GoalService.list_by_family(ctx.db, ctx.family_id)
        return [_ser_goal(r) for r in rows]

    async def get(self, ctx: McpContext, entity_id: UUID) -> dict:
        from app.services.budget.goal_service import GoalService
        return _ser_goal(await GoalService.get_by_id(ctx.db, entity_id, ctx.family_id))

    async def create(self, ctx: McpContext, data: dict) -> dict:
        from app.services.budget.goal_service import GoalService
        from app.schemas.budget import GoalCreate
        payload = dict(data)
        for field in ("start_date", "end_date"):
            if field in payload and isinstance(payload[field], str) and payload[field]:
                payload[field] = _parse_date(payload[field])
        r = await GoalService.create(ctx.db, ctx.family_id, GoalCreate(**payload))
        return _ser_goal(r)

    async def update(self, ctx: McpContext, entity_id: UUID, data: dict) -> dict:
        from app.services.budget.goal_service import GoalService
        from app.schemas.budget import GoalUpdate
        payload = dict(data)
        for field in ("start_date", "end_date"):
            if field in payload and isinstance(payload[field], str) and payload[field]:
                payload[field] = _parse_date(payload[field])
        r = await GoalService.update(ctx.db, entity_id, ctx.family_id, GoalUpdate(**payload))
        return _ser_goal(r)

    async def delete(self, ctx: McpContext, entity_id: UUID) -> None:
        from app.services.budget.goal_service import GoalService
        await GoalService.delete_by_id(ctx.db, entity_id, ctx.family_id)


def _ser_goal(g) -> dict:
    return {
        "id": str(g.id),
        "name": g.name,
        "category_id": str(g.category_id),
        "goal_type": g.goal_type,
        "target_amount": g.target_amount,
        "period": g.period,
        "is_active": g.is_active,
    }


# ── categorization rule ────────────────────────────────────────────────────

class RuleAdapter(ServiceAdapter):
    """Wraps CategorizationRuleService (BaseFamilyService[BudgetCategorizationRule])."""

    async def list(self, ctx: McpContext) -> list[dict]:
        from app.services.budget.categorization_rule_service import CategorizationRuleService
        rows = await CategorizationRuleService.list_rules(ctx.db, ctx.family_id)
        return [_ser_rule(r) for r in rows]

    async def get(self, ctx: McpContext, entity_id: UUID) -> dict:
        from app.services.budget.categorization_rule_service import CategorizationRuleService
        return _ser_rule(await CategorizationRuleService.get_by_id(ctx.db, entity_id, ctx.family_id))

    async def create(self, ctx: McpContext, data: dict) -> dict:
        from app.services.budget.categorization_rule_service import CategorizationRuleService
        from app.schemas.budget import CategorizationRuleCreate
        r = await CategorizationRuleService.create(ctx.db, ctx.family_id, CategorizationRuleCreate(**data))
        return _ser_rule(r)

    async def update(self, ctx: McpContext, entity_id: UUID, data: dict) -> dict:
        from app.services.budget.categorization_rule_service import CategorizationRuleService
        from app.schemas.budget import CategorizationRuleUpdate
        r = await CategorizationRuleService.update(ctx.db, entity_id, ctx.family_id, CategorizationRuleUpdate(**data))
        return _ser_rule(r)

    async def delete(self, ctx: McpContext, entity_id: UUID) -> None:
        from app.services.budget.categorization_rule_service import CategorizationRuleService
        await CategorizationRuleService.delete_by_id(ctx.db, entity_id, ctx.family_id)


def _ser_rule(r) -> dict:
    return {
        "id": str(r.id),
        "category_id": str(r.category_id),
        "rule_type": r.rule_type,
        "match_field": r.match_field,
        "pattern": r.pattern,
        "enabled": r.enabled,
        "priority": r.priority,
    }


# ── recurring transaction ──────────────────────────────────────────────────

class RecurringAdapter(ServiceAdapter):
    """Wraps RecurringTransactionService (BaseFamilyService[BudgetRecurringTransaction])."""

    async def list(self, ctx: McpContext) -> list[dict]:
        from app.services.budget.recurring_transaction_service import RecurringTransactionService
        rows = await RecurringTransactionService.list_by_family(ctx.db, ctx.family_id)
        return [_ser_recurring(r) for r in rows]

    async def get(self, ctx: McpContext, entity_id: UUID) -> dict:
        from app.services.budget.recurring_transaction_service import RecurringTransactionService
        return _ser_recurring(
            await RecurringTransactionService.get_by_id(ctx.db, entity_id, ctx.family_id)
        )

    async def create(self, ctx: McpContext, data: dict) -> dict:
        from app.services.budget.recurring_transaction_service import RecurringTransactionService
        from app.schemas.budget import RecurringTransactionCreate
        payload = dict(data)
        for field in ("start_date", "end_date"):
            if field in payload and isinstance(payload[field], str) and payload[field]:
                payload[field] = _parse_date(payload[field])
        r = await RecurringTransactionService.create(
            ctx.db, ctx.family_id, RecurringTransactionCreate(**payload)
        )
        return _ser_recurring(r)

    async def update(self, ctx: McpContext, entity_id: UUID, data: dict) -> dict:
        from app.services.budget.recurring_transaction_service import RecurringTransactionService
        from app.schemas.budget import RecurringTransactionUpdate
        payload = dict(data)
        for field in ("start_date", "end_date"):
            if field in payload and isinstance(payload[field], str) and payload[field]:
                payload[field] = _parse_date(payload[field])
        r = await RecurringTransactionService.update(
            ctx.db, entity_id, ctx.family_id, RecurringTransactionUpdate(**payload)
        )
        return _ser_recurring(r)

    async def delete(self, ctx: McpContext, entity_id: UUID) -> None:
        from app.services.budget.recurring_transaction_service import RecurringTransactionService
        await RecurringTransactionService.delete_by_id(ctx.db, entity_id, ctx.family_id)


def _ser_recurring(r) -> dict:
    return {
        "id": str(r.id),
        "name": r.name,
        "account_id": str(r.account_id),
        "amount": r.amount,
        "recurrence_type": r.recurrence_type,
        "is_active": r.is_active,
    }


# ── tag ────────────────────────────────────────────────────────────────────

class TagAdapter(ServiceAdapter):
    """Wraps TagService (BaseFamilyService[BudgetTag])."""

    async def list(self, ctx: McpContext) -> list[dict]:
        from app.services.budget.tag_service import TagService
        rows = await TagService.list_by_family(ctx.db, ctx.family_id)
        return [_ser_tag(r) for r in rows]

    async def get(self, ctx: McpContext, entity_id: UUID) -> dict:
        from app.services.budget.tag_service import TagService
        return _ser_tag(await TagService.get_by_id(ctx.db, entity_id, ctx.family_id))

    async def create(self, ctx: McpContext, data: dict) -> dict:
        from app.services.budget.tag_service import TagService
        from app.schemas.budget import TagCreate
        r = await TagService.create(ctx.db, ctx.family_id, TagCreate(**data))
        return _ser_tag(r)

    async def update(self, ctx: McpContext, entity_id: UUID, data: dict) -> dict:
        from app.services.budget.tag_service import TagService
        from app.schemas.budget import TagUpdate
        r = await TagService.update(ctx.db, entity_id, ctx.family_id, TagUpdate(**data))
        return _ser_tag(r)

    async def delete(self, ctx: McpContext, entity_id: UUID) -> None:
        from app.services.budget.tag_service import TagService
        await TagService.delete_by_id(ctx.db, entity_id, ctx.family_id)


def _ser_tag(t) -> dict:
    return {"id": str(t.id), "name": t.name, "color": t.color}


# ── saved_filter ───────────────────────────────────────────────────────────

class SavedFilterAdapter(ServiceAdapter):
    """Wraps SavedFilterService (BaseFamilyService[BudgetSavedFilter]).

    SavedFilterService.create requires a `created_by` UUID (users.id FK).
    Token-only sessions (user_id=None) cannot create saved filters — a
    ValueError is raised so dispatch_tool returns {"ok": false, "error": ...}.
    """

    async def list(self, ctx: McpContext) -> list[dict]:
        from app.services.budget.saved_filter_service import SavedFilterService
        rows = await SavedFilterService.list_by_family(ctx.db, ctx.family_id)
        return [_ser_filter(r) for r in rows]

    async def get(self, ctx: McpContext, entity_id: UUID) -> dict:
        from app.services.budget.saved_filter_service import SavedFilterService
        return _ser_filter(await SavedFilterService.get_by_id(ctx.db, entity_id, ctx.family_id))

    async def create(self, ctx: McpContext, data: dict) -> dict:
        from app.services.budget.saved_filter_service import SavedFilterService
        from app.schemas.budget import SavedFilterCreate
        if ctx.user_id is None:
            raise ValueError(
                "saved_filter create requires an authenticated user; "
                "not available for token-only MCP sessions"
            )
        r = await SavedFilterService.create(ctx.db, ctx.family_id, ctx.user_id, SavedFilterCreate(**data))
        return _ser_filter(r)

    async def update(self, ctx: McpContext, entity_id: UUID, data: dict) -> dict:
        from app.services.budget.saved_filter_service import SavedFilterService
        from app.schemas.budget import SavedFilterUpdate
        r = await SavedFilterService.update(ctx.db, entity_id, ctx.family_id, SavedFilterUpdate(**data))
        return _ser_filter(r)

    async def delete(self, ctx: McpContext, entity_id: UUID) -> None:
        from app.services.budget.saved_filter_service import SavedFilterService
        await SavedFilterService.delete_by_id(ctx.db, entity_id, ctx.family_id)


def _ser_filter(f) -> dict:
    return {
        "id": str(f.id),
        "name": f.name,
        "conditions": f.conditions,
        "conditions_op": f.conditions_op,
    }


# ── custom_report ──────────────────────────────────────────────────────────

class CustomReportAdapter(ServiceAdapter):
    """Wraps CustomReportService (BaseFamilyService[BudgetCustomReport]).

    CustomReportService.create requires a `created_by` UUID.
    """

    async def list(self, ctx: McpContext) -> list[dict]:
        from app.services.budget.custom_report_service import CustomReportService
        rows = await CustomReportService.list_by_family(ctx.db, ctx.family_id)
        return [_ser_report(r) for r in rows]

    async def get(self, ctx: McpContext, entity_id: UUID) -> dict:
        from app.services.budget.custom_report_service import CustomReportService
        return _ser_report(await CustomReportService.get_by_id(ctx.db, entity_id, ctx.family_id))

    async def create(self, ctx: McpContext, data: dict) -> dict:
        from app.services.budget.custom_report_service import CustomReportService
        from app.schemas.budget import CustomReportCreate
        if ctx.user_id is None:
            raise ValueError(
                "custom_report create requires an authenticated user; "
                "not available for token-only MCP sessions"
            )
        r = await CustomReportService.create(ctx.db, ctx.family_id, ctx.user_id, CustomReportCreate(**data))
        return _ser_report(r)

    async def update(self, ctx: McpContext, entity_id: UUID, data: dict) -> dict:
        from app.services.budget.custom_report_service import CustomReportService
        from app.schemas.budget import CustomReportUpdate
        r = await CustomReportService.update(ctx.db, entity_id, ctx.family_id, CustomReportUpdate(**data))
        return _ser_report(r)

    async def delete(self, ctx: McpContext, entity_id: UUID) -> None:
        from app.services.budget.custom_report_service import CustomReportService
        await CustomReportService.delete_by_id(ctx.db, entity_id, ctx.family_id)


def _ser_report(r) -> dict:
    return {"id": str(r.id), "name": r.name, "config": r.config}


# ── receipt_draft ──────────────────────────────────────────────────────────

class ReceiptDraftAdapter(ServiceAdapter):
    """Wraps ReceiptDraftService.

    ReceiptDraftService is NOT a BaseFamilyService subclass — it has its own
    custom get_by_id / list_pending / delete. No create via MCP (scans come
    from the /api/budget/transactions/scan-receipt route). Ops: list, get, delete.
    """

    async def list(self, ctx: McpContext) -> list[dict]:
        from app.services.budget.receipt_draft_service import ReceiptDraftService
        rows = await ReceiptDraftService.list_pending(ctx.db, ctx.family_id)
        return [_ser_draft(r) for r in rows]

    async def get(self, ctx: McpContext, entity_id: UUID) -> dict:
        from app.services.budget.receipt_draft_service import ReceiptDraftService
        return _ser_draft(await ReceiptDraftService.get_by_id(ctx.db, entity_id, ctx.family_id))

    async def delete(self, ctx: McpContext, entity_id: UUID) -> None:
        from app.services.budget.receipt_draft_service import ReceiptDraftService
        # ReceiptDraftService has no delete_by_id; use a direct delete
        draft = await ReceiptDraftService.get_by_id(ctx.db, entity_id, ctx.family_id)
        await ctx.db.delete(draft)
        await ctx.db.commit()


def _ser_draft(d) -> dict:
    return {
        "id": str(d.id),
        "account_id": str(d.account_id) if d.account_id else None,
        "status": d.status,
        "confidence": d.confidence,
        "scanned_data": d.scanned_data,
    }
