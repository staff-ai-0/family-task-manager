"""
MCP pydantic schemas for budget-domain entities.

These are the *MCP-facing* create/update schemas — deliberately minimal
compared to the full app schemas (no family_id, no read-only fields).
The adapters translate these to the real app service schemas before
calling into the service layer.
"""
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel


# ── account ────────────────────────────────────────────────────────────────

class AccountCreate(BaseModel):
    name: str
    account_type: str
    starting_balance: int = 0


class AccountUpdate(BaseModel):
    name: Optional[str] = None
    account_type: Optional[str] = None


# ── category_group ─────────────────────────────────────────────────────────

class CategoryGroupCreate(BaseModel):
    name: str
    sort_order: int = 0
    is_income: bool = False
    hidden: bool = False


class CategoryGroupUpdate(BaseModel):
    name: Optional[str] = None
    sort_order: Optional[int] = None
    is_income: Optional[bool] = None
    hidden: Optional[bool] = None


# ── category ───────────────────────────────────────────────────────────────

class CategoryCreate(BaseModel):
    name: str
    group_id: UUID
    sort_order: int = 0
    hidden: bool = False
    rollover_enabled: bool = True
    goal_amount: int = 0


class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    group_id: Optional[UUID] = None
    sort_order: Optional[int] = None
    hidden: Optional[bool] = None
    rollover_enabled: Optional[bool] = None
    goal_amount: Optional[int] = None


# ── payee ──────────────────────────────────────────────────────────────────

class PayeeCreate(BaseModel):
    name: str
    notes: Optional[str] = None
    is_favorite: bool = False


class PayeeUpdate(BaseModel):
    name: Optional[str] = None
    notes: Optional[str] = None
    is_favorite: Optional[bool] = None


# ── transaction ────────────────────────────────────────────────────────────

class TransactionCreate(BaseModel):
    account_id: UUID
    date: str  # ISO date string, e.g. "2026-06-01"
    amount: int  # cents; negative=expense, positive=income
    payee_id: Optional[UUID] = None
    payee_name: Optional[str] = None
    category_id: Optional[UUID] = None
    notes: Optional[str] = None
    cleared: bool = False


class TransactionUpdate(BaseModel):
    account_id: Optional[UUID] = None
    date: Optional[str] = None
    amount: Optional[int] = None
    payee_id: Optional[UUID] = None
    payee_name: Optional[str] = None
    category_id: Optional[UUID] = None
    notes: Optional[str] = None
    cleared: Optional[bool] = None


# ── allocation ─────────────────────────────────────────────────────────────

class AllocationCreate(BaseModel):
    category_id: UUID
    month: str  # ISO date string, first day of month, e.g. "2026-06-01"
    budgeted_amount: int = 0
    notes: Optional[str] = None


class AllocationUpdate(BaseModel):
    budgeted_amount: Optional[int] = None
    notes: Optional[str] = None


# ── goal ───────────────────────────────────────────────────────────────────

class GoalCreate(BaseModel):
    category_id: UUID
    goal_type: str  # "spending_limit" | "savings_target"
    target_amount: int
    period: str  # "monthly" | "quarterly" | "annual"
    start_date: str  # ISO date string
    name: str
    end_date: Optional[str] = None
    is_active: bool = True
    notes: Optional[str] = None


class GoalUpdate(BaseModel):
    category_id: Optional[UUID] = None
    goal_type: Optional[str] = None
    target_amount: Optional[int] = None
    period: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    is_active: Optional[bool] = None
    name: Optional[str] = None
    notes: Optional[str] = None


# ── categorization rule ────────────────────────────────────────────────────

class RuleCreate(BaseModel):
    category_id: UUID
    rule_type: str  # "exact" | "contains" | "startswith" | "regex"
    match_field: str  # "payee" | "description" | "both"
    pattern: str
    enabled: bool = True
    priority: int = 0
    notes: Optional[str] = None


class RuleUpdate(BaseModel):
    category_id: Optional[UUID] = None
    rule_type: Optional[str] = None
    match_field: Optional[str] = None
    pattern: Optional[str] = None
    enabled: Optional[bool] = None
    priority: Optional[int] = None
    notes: Optional[str] = None


# ── recurring transaction ──────────────────────────────────────────────────

class RecurringCreate(BaseModel):
    account_id: UUID
    name: str
    amount: int  # cents
    recurrence_type: str  # "daily"|"weekly"|"monthly_dayofmonth"|"monthly_dayofweek"|"yearly"
    start_date: str  # ISO date
    category_id: Optional[UUID] = None
    payee_id: Optional[UUID] = None
    description: Optional[str] = None
    recurrence_interval: int = 1
    end_date: Optional[str] = None
    is_active: bool = True
    end_mode: str = "never"


class RecurringUpdate(BaseModel):
    name: Optional[str] = None
    amount: Optional[int] = None
    recurrence_type: Optional[str] = None
    recurrence_interval: Optional[int] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    is_active: Optional[bool] = None
    category_id: Optional[UUID] = None
    payee_id: Optional[UUID] = None
    description: Optional[str] = None
    end_mode: Optional[str] = None


# ── tag ────────────────────────────────────────────────────────────────────

class TagCreate(BaseModel):
    name: str
    color: Optional[str] = None


class TagUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None


# ── saved_filter ───────────────────────────────────────────────────────────

class SavedFilterCreate(BaseModel):
    name: str
    conditions: list  # [{field, operator, value}]
    conditions_op: str = "and"


class SavedFilterUpdate(BaseModel):
    name: Optional[str] = None
    conditions: Optional[list] = None
    conditions_op: Optional[str] = None


# ── custom_report ──────────────────────────────────────────────────────────

class CustomReportCreate(BaseModel):
    name: str
    config: dict


class CustomReportUpdate(BaseModel):
    name: Optional[str] = None
    config: Optional[dict] = None
