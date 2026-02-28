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
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
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
    hidden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
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
    goal_amount: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="Monthly goal in cents")
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
    budgeted_amount: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="Amount in cents")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
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


class BudgetPayee(Base):
    """People or companies that receive or send money."""
    
    __tablename__ = "budget_payees"
    
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationships
    family: Mapped["Family"] = relationship("Family", back_populates="budget_payees")
    transactions: Mapped[list["BudgetTransaction"]] = relationship("BudgetTransaction", back_populates="payee")


class BudgetTransaction(Base):
    """Income and expense transactions."""
    
    __tablename__ = "budget_transactions"
    
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("budget_accounts.id", ondelete="CASCADE"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False, comment="Amount in cents (negative=expense, positive=income)")
    payee_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), ForeignKey("budget_payees.id", ondelete="SET NULL"), nullable=True)
    category_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), ForeignKey("budget_categories.id", ondelete="SET NULL"), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cleared: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reconciled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    imported_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="For deduplication of imported transactions")
    parent_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), ForeignKey("budget_transactions.id", ondelete="CASCADE"), nullable=True, comment="For split transactions")
    is_parent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="Is this a split parent transaction?")
    transfer_account_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), ForeignKey("budget_accounts.id", ondelete="SET NULL"), nullable=True, comment="Target account for transfers")
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
