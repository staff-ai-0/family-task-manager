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


class PayeeCreate(PayeeBase):
    """Schema for creating a payee"""
    pass


class PayeeUpdate(BaseModel):
    """Schema for updating a payee"""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    notes: Optional[str] = None


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
    pass


class TransactionUpdate(BaseModel):
    """Schema for updating a transaction"""
    account_id: Optional[UUID] = None
    date: Optional[DateType] = None
    amount: Optional[int] = None
    payee_id: Optional[UUID] = None
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


# Rebuild models to resolve forward references
CategoryWithGroup.model_rebuild()
CategoryGroupWithCategories.model_rebuild()
