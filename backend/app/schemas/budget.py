"""
Budget-related Pydantic schemas

Request and response models for budget management operations.
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from datetime import date as DateType, datetime
from uuid import UUID


# ============================================================================
# CATEGORY GROUP SCHEMAS
# ============================================================================

class CategoryGroupBase(BaseModel):
    """Base category group schema"""
    name: str = Field(..., min_length=1, max_length=100, description="Group name (e.g., 'Mandado', 'Servicios')")
    sort_order: int = Field(0, ge=0, description="Display order")
    is_income: bool = Field(False, description="Is this an income category group?")
    hidden: bool = Field(False, description="Hide from budget view")


class CategoryGroupCreate(CategoryGroupBase):
    """Schema for creating a category group"""
    pass


class CategoryGroupUpdate(BaseModel):
    """Schema for updating a category group"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    sort_order: Optional[int] = Field(None, ge=0)
    is_income: Optional[bool] = None
    hidden: Optional[bool] = None


class CategoryGroupResponse(CategoryGroupBase):
    """Category group response with metadata"""
    id: UUID
    family_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# CATEGORY SCHEMAS
# ============================================================================

class CategoryBase(BaseModel):
    """Base category schema"""
    name: str = Field(..., min_length=1, max_length=100, description="Category name (e.g., 'Fruta y Verdura', 'Luz')")
    group_id: UUID = Field(..., description="Parent category group")
    sort_order: int = Field(0, ge=0, description="Display order within group")
    hidden: bool = Field(False, description="Hide from budget view")
    rollover_enabled: bool = Field(True, description="Allow unused budget to roll over to next month")
    goal_amount: int = Field(0, ge=0, description="Monthly budget goal in cents")


class CategoryCreate(CategoryBase):
    """Schema for creating a category"""
    pass


class CategoryUpdate(BaseModel):
    """Schema for updating a category"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    group_id: Optional[UUID] = None
    sort_order: Optional[int] = Field(None, ge=0)
    hidden: Optional[bool] = None
    rollover_enabled: Optional[bool] = None
    goal_amount: Optional[int] = Field(None, ge=0)


class CategoryResponse(CategoryBase):
    """Category response with metadata"""
    id: UUID
    family_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# ACCOUNT SCHEMAS
# ============================================================================

class AccountBase(BaseModel):
    """Base account schema"""
    name: str = Field(..., min_length=1, max_length=200, description="Account name (e.g., 'BBVA Checking')")
    type: str = Field(..., description="Account type: checking, savings, credit, investment, loan, other")
    offbudget: bool = Field(False, description="Is this a tracking account (not part of budget)?")
    closed: bool = Field(False, description="Is this account closed?")
    notes: Optional[str] = Field(None, description="Optional notes")
    sort_order: int = Field(0, ge=0, description="Display order")
    starting_balance: int = Field(0, description="Initial account balance in cents at creation time")

    @field_validator('type')
    @classmethod
    def validate_type(cls, v):
        allowed_types = ['checking', 'savings', 'credit', 'investment', 'loan', 'other']
        if v not in allowed_types:
            raise ValueError(f'type must be one of: {", ".join(allowed_types)}')
        return v


class AccountCreate(AccountBase):
    """Schema for creating an account"""
    pass


class AccountUpdate(BaseModel):
    """Schema for updating an account"""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    type: Optional[str] = None
    offbudget: Optional[bool] = None
    closed: Optional[bool] = None
    notes: Optional[str] = None
    sort_order: Optional[int] = Field(None, ge=0)
    starting_balance: Optional[int] = Field(None, description="Initial account balance in cents")

    @field_validator('type')
    @classmethod
    def validate_type(cls, v):
        if v is not None:
            allowed_types = ['checking', 'savings', 'credit', 'investment', 'loan', 'other']
            if v not in allowed_types:
                raise ValueError(f'type must be one of: {", ".join(allowed_types)}')
        return v


class AccountResponse(AccountBase):
    """Account response with metadata"""
    id: UUID
    family_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# PAYEE SCHEMAS
# ============================================================================

class PayeeBase(BaseModel):
    """Base payee schema"""
    name: str = Field(..., min_length=1, max_length=200, description="Payee name (e.g., 'Oxxo', 'CFE')")
    notes: Optional[str] = Field(None, description="Optional notes")
    is_favorite: bool = Field(False, description="Mark as favorite payee")


class PayeeCreate(PayeeBase):
    """Schema for creating a payee"""
    pass


class PayeeUpdate(BaseModel):
    """Schema for updating a payee"""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    notes: Optional[str] = None
    is_favorite: Optional[bool] = None


class PayeeMergeRequest(BaseModel):
    """Schema for merging payees"""
    target_id: UUID = Field(..., description="Payee to keep (merge target)")
    source_ids: List[UUID] = Field(..., min_length=1, description="Payees to merge into target (will be deleted)")


class PayeeResponse(PayeeBase):
    """Payee response with metadata"""
    id: UUID
    family_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# TRANSACTION SCHEMAS
# ============================================================================

class TransactionBase(BaseModel):
    """Base transaction schema"""
    account_id: UUID = Field(..., description="Source account")
    date: DateType = Field(..., description="Transaction date")
    amount: int = Field(..., description="Amount in cents (negative for expenses, positive for income)")
    payee_id: Optional[UUID] = Field(None, description="Who you paid/received from")
    category_id: Optional[UUID] = Field(None, description="Budget category")
    notes: Optional[str] = Field(None, description="Optional notes")
    cleared: bool = Field(False, description="Has this transaction cleared?")
    reconciled: bool = Field(False, description="Has this been reconciled?")
    imported_id: Optional[str] = Field(None, max_length=255, description="External ID for deduplication")
    parent_id: Optional[UUID] = Field(None, description="Parent transaction for splits")
    is_parent: bool = Field(False, description="Is this a split parent?")
    transfer_account_id: Optional[UUID] = Field(None, description="Target account for transfers")


class TransactionCreate(TransactionBase):
    """Schema for creating a transaction"""
    payee_name: Optional[str] = Field(None, max_length=255, description="Payee name; creates payee if payee_id is absent")


class TransactionUpdate(BaseModel):
    """Schema for updating a transaction"""
    account_id: Optional[UUID] = None
    date: Optional[DateType] = None
    amount: Optional[int] = None
    payee_id: Optional[UUID] = None
    payee_name: Optional[str] = Field(None, max_length=255, description="Payee name; creates payee if payee_id is absent")
    category_id: Optional[UUID] = None
    notes: Optional[str] = None
    cleared: Optional[bool] = None
    reconciled: Optional[bool] = None
    imported_id: Optional[str] = Field(None, max_length=255)
    parent_id: Optional[UUID] = None
    is_parent: Optional[bool] = None
    transfer_account_id: Optional[UUID] = None


class TransactionResponse(TransactionBase):
    """Transaction response with metadata"""
    id: UUID
    family_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SplitChild(BaseModel):
    """One leg of a split transaction."""
    amount: int = Field(..., description="Amount in cents (sign matches parent)")
    category_id: Optional[UUID] = Field(None, description="Category for this leg")
    payee_id: Optional[UUID] = Field(None, description="Override payee for this leg")
    notes: Optional[str] = Field(None, description="Per-leg notes")


class SplitTransactionCreate(BaseModel):
    """Create a parent transaction with N child legs."""
    account_id: UUID
    date: DateType
    payee_id: Optional[UUID] = None
    payee_name: Optional[str] = Field(None, max_length=255)
    notes: Optional[str] = None
    cleared: bool = False
    reconciled: bool = False
    splits: List[SplitChild] = Field(..., min_length=2, description="At least 2 child legs required")


class SplitTransactionUpdate(BaseModel):
    """Replace the child legs of an existing split parent."""
    splits: List[SplitChild] = Field(..., min_length=2)


class SplitTransactionResponse(BaseModel):
    """Parent transaction plus its children."""
    parent: TransactionResponse
    children: List[TransactionResponse]
    total: int = Field(..., description="Sum of children amounts (must equal parent.amount)")


# ============================================================================
# ALLOCATION SCHEMAS
# ============================================================================

class AllocationBase(BaseModel):
    """Base budget allocation schema"""
    category_id: UUID = Field(..., description="Budget category")
    month: DateType = Field(..., description="Budget month (first day of month)")
    budgeted_amount: int = Field(0, ge=0, description="Budgeted amount in cents")
    notes: Optional[str] = Field(None, description="Optional notes")

    @field_validator('month')
    @classmethod
    def validate_month(cls, v):
        """Ensure month is the first day of the month"""
        if v.day != 1:
            raise ValueError('month must be the first day of the month')
        return v


class AllocationCreate(AllocationBase):
    """Schema for creating a budget allocation"""
    pass


class AllocationUpdate(BaseModel):
    """Schema for updating a budget allocation"""
    budgeted_amount: Optional[int] = Field(None, ge=0)
    notes: Optional[str] = None


class AllocationResponse(AllocationBase):
    """Budget allocation response with metadata"""
    id: UUID
    family_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# COMPLEX/COMPOSITE SCHEMAS
# ============================================================================

class CategoryWithGroup(CategoryResponse):
    """Category with its group information"""
    group: "CategoryGroupResponse"


class CategoryGroupWithCategories(CategoryGroupResponse):
    """Category group with all its categories"""
    categories: List["CategoryResponse"] = []


class MonthBudgetSummary(BaseModel):
    """Summary of budget for a given month"""
    month: DateType
    total_income: int = Field(0, description="Total budgeted income in cents")
    total_budgeted: int = Field(0, description="Total budgeted expenses in cents")
    total_spent: int = Field(0, description="Total actual spending in cents")
    to_budget: int = Field(0, description="Amount available to budget in cents")
    category_groups: List[CategoryGroupWithCategories] = []


class AccountBalance(BaseModel):
    """Account with calculated balance"""
    account: AccountResponse
    balance: int = Field(0, description="Current balance in cents")
    cleared_balance: int = Field(0, description="Cleared balance in cents")


class CategoryWithActivity(CategoryResponse):
    """Category with spending activity for a month"""
    budgeted: int = Field(0, description="Budgeted amount in cents")
    activity: int = Field(0, description="Actual spending in cents")
    available: int = Field(0, description="Remaining available in cents")


# ============================================================================
# CATEGORIZATION RULE SCHEMAS
# ============================================================================

class CategorizationRuleBase(BaseModel):
    """Base categorization rule schema"""
    category_id: UUID = Field(..., description="Target category for matching transactions")
    rule_type: str = Field(
        ..., 
        description="Match type: 'exact', 'contains', 'startswith', 'regex'"
    )
    match_field: str = Field(
        ...,
        description="Field to match: 'payee', 'description', 'both'"
    )
    pattern: str = Field(..., min_length=1, max_length=500, description="Pattern to match (case-insensitive)")
    enabled: bool = Field(True, description="Is this rule enabled?")
    priority: int = Field(0, ge=-1000, le=1000, description="Higher priority rules match first")
    notes: Optional[str] = Field(None, description="Optional notes about the rule")


class RuleAction(BaseModel):
    """Single action for advanced rule processing"""
    field: str = Field(..., description="'category', 'payee', 'notes'")
    operation: str = Field(..., description="'set', 'append', 'prepend'")
    value: str = Field(..., description="Value to set/append/prepend (UUID string for category/payee)")


class CategorizationRuleCreate(CategorizationRuleBase):
    """Schema for creating a categorization rule"""
    actions: Optional[List[RuleAction]] = Field(None, description="Advanced multi-field actions")


class CategorizationRuleUpdate(BaseModel):
    """Schema for updating a categorization rule"""
    category_id: Optional[UUID] = None
    rule_type: Optional[str] = None
    match_field: Optional[str] = None
    pattern: Optional[str] = Field(None, min_length=1, max_length=500)
    enabled: Optional[bool] = None
    priority: Optional[int] = Field(None, ge=-1000, le=1000)
    notes: Optional[str] = None
    actions: Optional[List[RuleAction]] = Field(None, description="Advanced multi-field actions")


class CategorizationRuleResponse(CategorizationRuleBase):
    """Categorization rule response with metadata"""
    id: UUID
    family_id: UUID
    actions: Optional[List[RuleAction]] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CategorizationSuggestion(BaseModel):
    """Suggested category for a transaction"""
    category_id: Optional[UUID] = Field(None, description="Suggested category ID or None if no match")
    rule_id: Optional[UUID] = Field(None, description="ID of the matching rule")
    confidence: str = Field("low", description="Confidence level: 'low', 'medium', 'high'")


# ============================================================================
# GOAL SCHEMAS
# ============================================================================

class GoalBase(BaseModel):
    """Base goal schema"""
    category_id: UUID = Field(..., description="Category to track goal for")
    goal_type: str = Field(..., description="Goal type: 'spending_limit' or 'savings_target'")
    target_amount: int = Field(..., ge=0, description="Target amount in cents")
    period: str = Field(..., description="Period: 'monthly', 'quarterly', 'annual'")
    start_date: DateType = Field(..., description="Goal start date")
    end_date: Optional[DateType] = Field(None, description="Goal end date (null = ongoing)")
    is_active: bool = Field(True, description="Is goal currently active?")
    name: str = Field(..., min_length=1, max_length=255, description="Human-readable goal name")
    notes: Optional[str] = Field(None, description="Optional notes about the goal")


class GoalCreate(GoalBase):
    """Schema for creating a goal"""
    pass


class GoalUpdate(BaseModel):
    """Schema for updating a goal"""
    category_id: Optional[UUID] = None
    goal_type: Optional[str] = None
    target_amount: Optional[int] = Field(None, ge=0)
    period: Optional[str] = None
    start_date: Optional[DateType] = None
    end_date: Optional[DateType] = None
    is_active: Optional[bool] = None
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    notes: Optional[str] = None


class GoalResponse(GoalBase):
    """Goal response with metadata"""
    id: UUID
    family_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class GoalProgress(BaseModel):
    """Goal progress tracking"""
    goal_id: UUID = Field(..., description="Goal ID")
    goal_name: str = Field(..., description="Goal name")
    goal_type: str = Field(..., description="Goal type: 'spending_limit' or 'savings_target'")
    target_amount: int = Field(..., description="Target amount in cents")
    actual_amount: int = Field(..., description="Actual amount in cents")
    period: str = Field(..., description="Period: 'monthly', 'quarterly', 'annual'")
    start_date: DateType = Field(..., description="Goal start date")
    end_date: Optional[DateType] = Field(None, description="Goal end date (null = ongoing)")
    on_track: bool = Field(..., description="Is goal on track?")
    percentage: float = Field(..., ge=0, le=100, description="Progress percentage (0-100)")


# ============================================================================
# RECURRING TRANSACTION SCHEMAS
# ============================================================================

class RecurringTransactionBase(BaseModel):
    """Base recurring transaction schema"""
    account_id: UUID = Field(..., description="Account ID")
    category_id: Optional[UUID] = Field(None, description="Category ID (optional)")
    payee_id: Optional[UUID] = Field(None, description="Payee ID (optional)")
    name: str = Field(..., min_length=1, max_length=255, description="Template name (e.g., 'Monthly Rent')")
    description: Optional[str] = Field(None, description="Optional description")
    amount: int = Field(..., description="Amount in cents (negative=expense, positive=income)")
    recurrence_type: str = Field(
        ...,
        description="'daily', 'weekly', 'monthly_dayofmonth', 'monthly_dayofweek', 'yearly'"
    )
    recurrence_interval: int = Field(1, ge=1, le=52, description="Repeat every N periods")
    recurrence_pattern: Optional[dict] = Field(None, description="Pattern-specific configuration (JSON)")
    start_date: DateType = Field(..., description="First occurrence date")
    end_date: Optional[DateType] = Field(None, description="Last occurrence date (null = ongoing)")
    is_active: bool = Field(True, description="Is template currently active?")
    end_mode: str = Field("never", description="'never', 'on_date', 'after_n'")
    occurrence_limit: Optional[int] = Field(None, ge=1, description="Max occurrences for after_n mode")
    occurrence_count: int = Field(0, ge=0, description="Current posted count")
    weekend_behavior: str = Field("none", description="'none', 'before' (shift to Fri), 'after' (shift to Mon)")


class RecurringTransactionCreate(RecurringTransactionBase):
    """Schema for creating a recurring transaction"""
    pass


class RecurringTransactionUpdate(BaseModel):
    """Schema for updating a recurring transaction"""
    account_id: Optional[UUID] = None
    category_id: Optional[UUID] = None
    payee_id: Optional[UUID] = None
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    amount: Optional[int] = None
    recurrence_type: Optional[str] = None
    recurrence_interval: Optional[int] = Field(None, ge=1, le=52)
    recurrence_pattern: Optional[dict] = None
    start_date: Optional[DateType] = None
    end_date: Optional[DateType] = None
    is_active: Optional[bool] = None
    end_mode: Optional[str] = None
    occurrence_limit: Optional[int] = Field(None, ge=1)
    occurrence_count: Optional[int] = Field(None, ge=0)
    weekend_behavior: Optional[str] = None


class RecurringTransactionResponse(RecurringTransactionBase):
    """Recurring transaction response with metadata"""
    id: UUID
    family_id: UUID
    last_generated_date: Optional[DateType] = None
    next_due_date: Optional[DateType] = None
    occurrence_count: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RecurringTransactionNextDate(BaseModel):
    """Response with next due date for a recurring transaction"""
    next_due_date: Optional[DateType] = Field(..., description="Next scheduled date or None if no more occurrences")
    is_expired: bool = Field(..., description="True if end_date has passed")
    occurrences_remaining: Optional[int] = Field(None, description="Estimated occurrences remaining (None if ongoing)")


# ============================================================================
# MONTH LOCKING SCHEMAS
# ============================================================================

class MonthClosureResponse(BaseModel):
    """Response for closing a month"""
    month: DateType = Field(..., description="Month that was closed")
    closed_at: datetime = Field(..., description="When the month was closed")
    allocation_count: int = Field(..., ge=0, description="Number of allocations closed")


class MonthReopenResponse(BaseModel):
    """Response for reopening a month"""
    month: DateType = Field(..., description="Month that was reopened")
    allocation_count: int = Field(..., ge=0, description="Number of allocations reopened")


class MonthStatusResponse(BaseModel):
    """Response with month closure status"""
    month: DateType = Field(..., description="The month")
    is_closed: bool = Field(..., description="Is this month closed?")
    closed_at: Optional[datetime] = Field(None, description="When closed (null if open)")
    allocation_count: int = Field(..., ge=0, description="Number of allocations")


class ClosedMonthInfo(BaseModel):
    """Information about a closed month"""
    month: DateType = Field(..., description="The closed month")
    closed_at: datetime = Field(..., description="When it was closed")
    allocation_count: int = Field(..., ge=0, description="Number of allocations")


# ============================================================================
# SAVED FILTER SCHEMAS
# ============================================================================

class SavedFilterCreate(BaseModel):
    """Schema for creating a saved transaction filter"""
    name: str = Field(..., min_length=1, max_length=200)
    conditions: list = Field(..., description="[{field, operator, value}]")
    conditions_op: str = Field("and", description="'and' or 'or'")


class SavedFilterUpdate(BaseModel):
    """Schema for updating a saved filter"""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    conditions: Optional[list] = None
    conditions_op: Optional[str] = None


class SavedFilterResponse(BaseModel):
    """Saved filter response with metadata"""
    id: UUID
    family_id: UUID
    name: str
    conditions: list
    conditions_op: str
    created_by: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# TAG SCHEMAS
# ============================================================================

class TagCreate(BaseModel):
    """Schema for creating a tag"""
    name: str = Field(..., min_length=1, max_length=100)
    color: Optional[str] = Field(None, max_length=20)


class TagUpdate(BaseModel):
    """Schema for updating a tag"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    color: Optional[str] = None


class TagResponse(BaseModel):
    """Tag response with metadata"""
    id: UUID
    family_id: UUID
    name: str
    color: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TransactionTagsUpdate(BaseModel):
    """Schema for setting tags on a transaction"""
    tag_ids: List[UUID]


# ============================================================================
# AUTO-FILL SCHEMAS
# ============================================================================

class AutoFillRequest(BaseModel):
    """Request for auto-filling budget allocations"""
    target_month: DateType = Field(..., description="First day of the month to fill")
    strategy: str = Field(..., description="Strategy: 'copy_previous', 'average_3', 'average_6', 'average_12', 'from_goals'")
    overwrite_existing: bool = Field(False, description="Overwrite existing allocations?")

    @field_validator('target_month')
    @classmethod
    def validate_month(cls, v):
        if v.day != 1:
            raise ValueError('target_month must be the first day of the month')
        return v

    @field_validator('strategy')
    @classmethod
    def validate_strategy(cls, v):
        allowed = ['copy_previous', 'average_3', 'average_6', 'average_12', 'from_goals']
        if v not in allowed:
            raise ValueError(f'strategy must be one of: {", ".join(allowed)}')
        return v


class AutoFillResponse(BaseModel):
    """Response for auto-fill operation"""
    filled_count: int
    skipped_count: int


# ============================================================================
# CUSTOM REPORT SCHEMAS
# ============================================================================

class CustomReportCreate(BaseModel):
    """Schema for creating a custom report"""
    name: str = Field(..., min_length=1, max_length=200)
    config: dict = Field(...)


class CustomReportUpdate(BaseModel):
    """Schema for updating a custom report"""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    config: Optional[dict] = None


class CustomReportResponse(BaseModel):
    """Custom report response with metadata"""
    id: UUID
    family_id: UUID
    name: str
    config: dict
    created_by: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# RECEIPT DRAFT SCHEMAS (HITL review queue)
# ============================================================================

class ReceiptDraftApprove(BaseModel):
    """Fields the human can override before approving a receipt draft."""
    date: Optional[DateType] = Field(None, description="Transaction date (override extracted value)")
    amount: Optional[int] = Field(None, description="Amount in cents, negative for expenses")
    payee_name: Optional[str] = Field(None, max_length=200, description="Payee name")
    category_id: Optional[UUID] = Field(None, description="Budget category")
    notes: Optional[str] = Field(None, max_length=500)


class ReceiptDraftResponse(BaseModel):
    """Receipt draft as returned by the API."""
    id: UUID
    family_id: UUID
    account_id: UUID
    scanned_data: dict
    confidence: float
    status: str
    transaction_id: Optional[UUID]
    image_url: Optional[str] = None
    created_at: datetime
    reviewed_at: Optional[datetime]

    class Config:
        from_attributes = True


# Rebuild models to resolve forward references
CategoryWithGroup.model_rebuild()
CategoryGroupWithCategories.model_rebuild()
