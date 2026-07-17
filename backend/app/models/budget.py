"""
Budget-related SQLAlchemy models for envelope budgeting system.

This module contains all models for the budget management feature:
- Category Groups and Categories
- Accounts (checking, savings, credit cards, etc.)
- Transactions (income and expenses)
- Payees (people/companies)
- Budget Allocations (monthly budget amounts)
"""
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from app.models.family import Family

from sqlalchemy import BigInteger, Boolean, CHAR, Date, DateTime, Float, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base


class BudgetCategoryGroup(Base):
    """Category groups organize budget categories (e.g., 'Mandado', 'Servicios', 'Entretenimiento')."""

    __tablename__ = "budget_category_groups"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_income: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_transfer: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="Transfer bucket (between accounts / card payments / ATM) — excluded from spending & income reports")
    hidden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True, comment="Soft delete timestamp")
    deleted_by_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, comment="User who deleted this group")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationships
    categories: Mapped[list["BudgetCategory"]] = relationship("BudgetCategory", back_populates="group", cascade="all, delete-orphan")
    family: Mapped["Family"] = relationship("Family", back_populates="budget_category_groups")

class BudgetCategory(Base):
    """Individual budget categories within a group."""
    
    __tablename__ = "budget_categories"
    
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True)
    group_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("budget_category_groups.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    rollover_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    goal_amount: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False, comment="Monthly goal in cents")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="Free-text envelope notes (rules of use, reminders)")
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True, comment="Soft delete timestamp")
    deleted_by_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, comment="User who deleted this category")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    group: Mapped["BudgetCategoryGroup"] = relationship("BudgetCategoryGroup", back_populates="categories")
    family: Mapped["Family"] = relationship("Family", back_populates="budget_categories")
    allocations: Mapped[list["BudgetAllocation"]] = relationship("BudgetAllocation", back_populates="category", cascade="all, delete-orphan")
    transactions: Mapped[list["BudgetTransaction"]] = relationship("BudgetTransaction", back_populates="category", foreign_keys="BudgetTransaction.category_id")


class BudgetAllocation(Base):
    """Monthly budget allocations for categories."""
    
    __tablename__ = "budget_allocations"
    __table_args__ = (
        UniqueConstraint("category_id", "month", name="uq_allocation_category_month"),
    )
    
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True)
    category_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("budget_categories.id", ondelete="CASCADE"), nullable=False)
    month: Mapped[date] = mapped_column(Date, nullable=False, comment="First day of the month")
    budgeted_amount: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False, comment="Amount in cents")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, comment="Month close timestamp (null = open)")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationships
    category: Mapped["BudgetCategory"] = relationship("BudgetCategory", back_populates="allocations")
    family: Mapped["Family"] = relationship("Family", back_populates="budget_allocations")


class BudgetAccount(Base):
    """Bank accounts, credit cards, and other financial accounts."""
    
    __tablename__ = "budget_accounts"
    
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False, comment="checking, savings, credit, investment, loan, other")
    offbudget: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="Tracking account (not part of budget)")
    closed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    starting_balance: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False, comment="Initial account balance in cents at creation time")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="MXN", comment="ISO 4217 currency code (e.g. MXN, USD, EUR)")
    card_last4: Mapped[Optional[str]] = mapped_column(
        CHAR(4), nullable=True,
        comment="Last 4 digits of the card associated with this account; used for receipt auto-match",
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True, comment="Soft delete timestamp")
    deleted_by_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, comment="User who deleted this account")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    family: Mapped["Family"] = relationship("Family", back_populates="budget_accounts")
    transactions: Mapped[list["BudgetTransaction"]] = relationship(
        "BudgetTransaction", 
        back_populates="account", 
        foreign_keys="BudgetTransaction.account_id",
        cascade="all, delete-orphan"
    )
    transfer_transactions: Mapped[list["BudgetTransaction"]] = relationship(
        "BudgetTransaction",
        back_populates="transfer_account",
        foreign_keys="BudgetTransaction.transfer_account_id"
    )
    recurring_transactions: Mapped[list["BudgetRecurringTransaction"]] = relationship(
        "BudgetRecurringTransaction",
        back_populates="account",
        cascade="all, delete-orphan"
    )


class BudgetPayee(Base):
    """People or companies that receive or send money."""
    
    __tablename__ = "budget_payees"
    
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    default_category_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("budget_categories.id", ondelete="SET NULL"),
        nullable=True,
        comment="Learned category — transactions for this payee inherit it (Actual-style payee learning)",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    family: Mapped["Family"] = relationship("Family", back_populates="budget_payees")
    default_category: Mapped[Optional["BudgetCategory"]] = relationship("BudgetCategory", foreign_keys=[default_category_id])
    transactions: Mapped[list["BudgetTransaction"]] = relationship("BudgetTransaction", back_populates="payee")
    recurring_transactions: Mapped[list["BudgetRecurringTransaction"]] = relationship("BudgetRecurringTransaction", back_populates="payee")


class BudgetTransaction(Base):
    """Income and expense transactions."""

    __tablename__ = "budget_transactions"

    # Hot path: transaction list is always `WHERE family_id = ? ORDER BY date
    # DESC`. Composite (family_id, date DESC) lets Postgres filter + sort in a
    # single index scan. Declared here to mirror the ops migration.
    __table_args__ = (
        Index(
            "ix_budget_transactions_family_date",
            "family_id",
            text("date DESC"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("budget_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="Amount in cents (negative=expense, positive=income)")
    card_last4: Mapped[Optional[str]] = mapped_column(CHAR(4), nullable=True)
    iva_cents: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    fx_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6), nullable=True)
    original_amount_cents: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    original_currency: Mapped[Optional[str]] = mapped_column(CHAR(3), nullable=True)
    payee_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), ForeignKey("budget_payees.id", ondelete="SET NULL"), nullable=True, index=True)
    category_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), ForeignKey("budget_categories.id", ondelete="SET NULL"), nullable=True, index=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cleared: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reconciled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    imported_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="For deduplication of imported transactions")
    parent_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), ForeignKey("budget_transactions.id", ondelete="CASCADE"), nullable=True, comment="For split transactions")
    is_parent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="Is this a split parent transaction?")
    transfer_account_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), ForeignKey("budget_accounts.id", ondelete="SET NULL"), nullable=True, comment="Target account for transfers")
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True, comment="Soft delete timestamp")
    deleted_by_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, comment="User who deleted this transaction")
    created_by_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="User who originally created this transaction (for per-user last-used account fallback in receipt scanner)",
    )
    receipt_image_path: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="GCS object key under GCS_RECEIPT_BUCKET; null if no image stored.",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    family: Mapped["Family"] = relationship("Family", back_populates="budget_transactions")
    account: Mapped["BudgetAccount"] = relationship("BudgetAccount", back_populates="transactions", foreign_keys=[account_id])
    transfer_account: Mapped[Optional["BudgetAccount"]] = relationship("BudgetAccount", back_populates="transfer_transactions", foreign_keys=[transfer_account_id])
    payee: Mapped[Optional["BudgetPayee"]] = relationship("BudgetPayee", back_populates="transactions")
    category: Mapped[Optional["BudgetCategory"]] = relationship("BudgetCategory", back_populates="transactions", foreign_keys=[category_id])
    parent_transaction: Mapped[Optional["BudgetTransaction"]] = relationship("BudgetTransaction", remote_side=[id], back_populates="split_transactions")
    split_transactions: Mapped[list["BudgetTransaction"]] = relationship("BudgetTransaction", back_populates="parent_transaction", cascade="all, delete-orphan")
    items: Mapped[list["BudgetTransactionItem"]] = relationship(
        "BudgetTransactionItem",
        back_populates="transaction",
        cascade="all, delete-orphan",
    )


class BudgetMonthHold(Base):
    """Money held back from a month's Ready-to-Assign for the NEXT month.

    Actual Budget's "hold for next month": RTA(month) drops by amount_cents
    and RTA(month+1) gains it. One row per (family, month); amount 0 = no
    hold (rows are upserted, not deleted, to keep the history readable).
    """
    __tablename__ = "budget_month_holds"
    __table_args__ = (
        UniqueConstraint("family_id", "month", name="uq_month_hold_family_month"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True)
    month: Mapped[date] = mapped_column(Date, nullable=False, comment="First day of the month the hold is taken FROM")
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class BudgetSyncState(Base):
    """Tracks synchronization state between family points and budget system."""
    
    __tablename__ = "budget_sync_state"
    
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    last_sync_to_budget: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, comment="Last time points were synced to budget")
    last_sync_from_budget: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, comment="Last time budget transactions were synced")
    synced_point_transactions: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default='{}', comment="Map of FTM transaction ID -> budget transaction ID")
    synced_budget_transactions: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default='{}', comment="Map of budget transaction ID -> FTM transaction ID")
    sync_errors: Mapped[list] = mapped_column(JSONB, nullable=False, server_default='[]', comment="Recent sync errors")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationships
    family: Mapped["Family"] = relationship("Family", back_populates="budget_sync_state")


class BudgetCategorizationRule(Base):
    """Rules for automatically categorizing transactions based on payee or description patterns."""
    
    __tablename__ = "budget_categorization_rules"
    
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True)
    category_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("budget_categories.id", ondelete="CASCADE"), nullable=False)
    
    # Rule matching criteria
    rule_type: Mapped[str] = mapped_column(String(50), nullable=False, comment="'exact', 'contains', 'startswith', 'regex'")
    match_field: Mapped[str] = mapped_column(String(50), nullable=False, comment="'payee', 'description', 'both'")
    pattern: Mapped[str] = mapped_column(String(500), nullable=False, comment="Pattern to match (case-insensitive)")
    
    # Rule behavior
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="Higher priority rules match first")

    # Advanced actions (Wave 2)
    actions: Mapped[Optional[list]] = mapped_column(
        JSONB, nullable=True, default=None,
        comment="Multi-field actions: [{field, operation, value}, ...]"
    )

    # Metadata
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    family: Mapped["Family"] = relationship("Family", back_populates="budget_categorization_rules")
    category: Mapped["BudgetCategory"] = relationship("BudgetCategory", foreign_keys=[category_id])


class BudgetGoal(Base):
    """Spending goals and targets for categories (monthly or annual).
    
    Goals track spending targets independent of allocations.
    Example: "Spend no more than $200 on groceries this month"
    """
    
    __tablename__ = "budget_goals"
    
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True)
    category_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("budget_categories.id", ondelete="CASCADE"), nullable=False)
    
    # Goal specification
    goal_type: Mapped[str] = mapped_column(String(50), nullable=False, comment="'spending_limit' or 'savings_target'")
    target_amount: Mapped[int] = mapped_column(Integer, nullable=False, comment="Target amount in cents")
    period: Mapped[str] = mapped_column(String(50), nullable=False, comment="'monthly', 'quarterly', 'annual'")
    
    # Time period
    start_date: Mapped[date] = mapped_column(Date, nullable=False, comment="Goal start date")
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, comment="Goal end date (null = ongoing)")
    
    # Tracking
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="Whether goal is currently active")
    name: Mapped[str] = mapped_column(String(255), nullable=False, comment="Human-readable goal name")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Metadata
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationships
    family: Mapped["Family"] = relationship("Family", back_populates="budget_goals")
    category: Mapped["BudgetCategory"] = relationship("BudgetCategory", foreign_keys=[category_id])


class BudgetRecurringTransaction(Base):
    """Recurring/scheduled transaction templates.
    
    Templates for automatically generating transactions on a schedule:
    - Daily: every N days
    - Weekly: every N weeks on specific days (Mon-Sun)
    - Monthly: every N months on specific day-of-month or day-of-week
    """
    
    __tablename__ = "budget_recurring_transactions"
    
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("budget_accounts.id", ondelete="CASCADE"), nullable=False)
    category_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), ForeignKey("budget_categories.id", ondelete="SET NULL"), nullable=True)
    payee_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), ForeignKey("budget_payees.id", ondelete="SET NULL"), nullable=True)
    
    # Transaction template data
    name: Mapped[str] = mapped_column(String(255), nullable=False, comment="Template name (e.g., 'Monthly Rent')")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="Amount in cents (negative=expense, positive=income)")
    
    # Recurrence pattern
    recurrence_type: Mapped[str] = mapped_column(
        String(50), 
        nullable=False, 
        comment="'daily', 'weekly', 'monthly_dayofmonth', 'monthly_dayofweek', 'yearly'"
    )
    # Recurrence frequency: every N days/weeks/months
    recurrence_interval: Mapped[int] = mapped_column(Integer, default=1, nullable=False, comment="Repeat every N periods")
    
    # Pattern-specific fields (JSON for flexibility)
    # For weekly: list of day numbers (0=Mon, 1=Tue, ..., 6=Sun)
    # For monthly_dayofweek: {"week": 0-4 or -1 (last), "day": 0-6}
    # For monthly_dayofmonth: day number (1-31)
    recurrence_pattern: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True, comment="Pattern-specific configuration")
    
    # Scheduling
    start_date: Mapped[date] = mapped_column(Date, nullable=False, comment="First occurrence date")
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, comment="Last occurrence date (null = ongoing)")

    # Schedule end modes
    end_mode: Mapped[str] = mapped_column(String(20), default="never", nullable=False, comment="'never', 'on_date', 'after_n'")
    occurrence_limit: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="Max occurrences for after_n mode")
    occurrence_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="Current posted count")
    weekend_behavior: Mapped[str] = mapped_column(String(20), default="none", nullable=False, comment="'none', 'before' (Fri), 'after' (Mon)")

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_generated_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, comment="Last date a transaction was auto-generated")
    next_due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, comment="Next scheduled date")
    
    # Metadata
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationships
    family: Mapped["Family"] = relationship("Family", back_populates="budget_recurring_transactions")
    account: Mapped["BudgetAccount"] = relationship("BudgetAccount", back_populates="recurring_transactions")
    category: Mapped[Optional["BudgetCategory"]] = relationship("BudgetCategory", foreign_keys=[category_id])
    payee: Mapped[Optional["BudgetPayee"]] = relationship("BudgetPayee", foreign_keys=[payee_id])


class BudgetSavedFilter(Base):
    """Saved transaction filter presets for quick access."""

    __tablename__ = "budget_saved_filters"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    conditions: Mapped[list] = mapped_column(JSONB, nullable=False, comment="[{field, operator, value}, ...]")
    conditions_op: Mapped[str] = mapped_column(String(10), default="and", nullable=False, comment="'and' or 'or'")
    created_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    family: Mapped["Family"] = relationship("Family")


class BudgetTag(Base):
    """Tags for labeling transactions."""

    __tablename__ = "budget_tags"
    __table_args__ = (
        UniqueConstraint("family_id", "name", name="uq_tag_family_name"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    color: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    family: Mapped["Family"] = relationship("Family")


class BudgetTransactionTag(Base):
    """Many-to-many link between transactions and tags."""

    __tablename__ = "budget_transaction_tags"
    __table_args__ = (
        UniqueConstraint("transaction_id", "tag_id", name="uq_transaction_tag"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    transaction_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("budget_transactions.id", ondelete="CASCADE"), nullable=False, index=True)
    tag_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("budget_tags.id", ondelete="CASCADE"), nullable=False, index=True)


class BudgetCustomReport(Base):
    """Saved custom report configurations for reusable budget analytics."""

    __tablename__ = "budget_custom_reports"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, comment="Report configuration: graph_type, group_by, date_range, etc.")
    created_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    family: Mapped["Family"] = relationship("Family", back_populates="budget_custom_reports")


class BudgetReceiptDraft(Base):
    """Pending receipt scan queued for human review (HITL).

    Created when scan_and_create_transaction extracts data below the
    confidence threshold or cannot read a total amount. A parent opens
    the review queue, corrects the pre-filled fields, and either
    approves (which creates the real BudgetTransaction) or rejects
    (which discards the draft).
    """

    __tablename__ = "budget_receipt_drafts"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True)
    # Nullable: a family with ZERO accounts can still scan — the draft holds
    # the extraction and the approver picks/creates an account at review time.
    account_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), ForeignKey("budget_accounts.id", ondelete="CASCADE"), nullable=True)
    scanned_data: Mapped[dict] = mapped_column(JSONB, nullable=False, comment="Extracted receipt fields: date, total_amount, payee_name, items, currency")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, comment="Vision model confidence 0.0–1.0")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", comment="pending | approved | rejected")
    transaction_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), ForeignKey("budget_transactions.id", ondelete="SET NULL"), nullable=True, comment="Populated on approval")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    image_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True, comment="Stored receipt image path")

    # Relationships
    family: Mapped["Family"] = relationship("Family")
    account: Mapped["BudgetAccount"] = relationship("BudgetAccount")


class BudgetTransactionItem(Base):
    """Line items extracted from a receipt scan or manual transaction edit."""

    __tablename__ = "budget_transaction_items"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("families.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    transaction_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("budget_transactions.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False)
    qty: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 3), nullable=True)
    unit_price_cents: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    total_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    category_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("budget_categories.id", ondelete="SET NULL"),
        nullable=True,
    )
    brand: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False,
    )

    transaction: Mapped["BudgetTransaction"] = relationship(
        "BudgetTransaction", back_populates="items"
    )
    category: Mapped[Optional["BudgetCategory"]] = relationship(
        "BudgetCategory", foreign_keys=[category_id]
    )
