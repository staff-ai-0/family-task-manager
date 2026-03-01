from sqlalchemy import Column, String, Boolean, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
import secrets
import string

from app.core.database import Base


def generate_join_code(length: int = 6) -> str:
    """Generate a short, human-readable join code (uppercase alphanumeric, no ambiguous chars)"""
    # Exclude ambiguous characters: 0/O, 1/I/L
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


class Family(Base):
    """Family group model"""
    __tablename__ = "families"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    name = Column(String(100), nullable=False)
    created_by = Column(UUID(as_uuid=True), nullable=True)  # Nullable during creation, set after user created
    join_code = Column(String(10), unique=True, nullable=True, index=True)  # Short code for family invites
    is_active = Column(Boolean, default=True, nullable=False)
    
    # Actual Budget sync configuration
    actual_budget_file_id = Column(String(255), nullable=True, comment="Actual Budget file ID for this family")
    actual_budget_sync_enabled = Column(Boolean, default=False, nullable=False, comment="Enable sync with Actual Budget")
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    members = relationship("User", back_populates="family")
    # Legacy task relationship (to be removed after migration)
    tasks = relationship("Task", back_populates="family", cascade="all, delete-orphan")
    # New template/assignment relationships
    task_templates = relationship("TaskTemplate", back_populates="family", cascade="all, delete-orphan")
    task_assignments = relationship("TaskAssignment", back_populates="family", cascade="all, delete-orphan")
    rewards = relationship("Reward", back_populates="family", cascade="all, delete-orphan")
    consequences = relationship("Consequence", back_populates="family", cascade="all, delete-orphan")
    
    # Budget relationships
    budget_category_groups = relationship("BudgetCategoryGroup", back_populates="family", cascade="all, delete-orphan")
    budget_categories = relationship("BudgetCategory", back_populates="family", cascade="all, delete-orphan")
    budget_allocations = relationship("BudgetAllocation", back_populates="family", cascade="all, delete-orphan")
    budget_accounts = relationship("BudgetAccount", back_populates="family", cascade="all, delete-orphan")
    budget_payees = relationship("BudgetPayee", back_populates="family", cascade="all, delete-orphan")
    budget_transactions = relationship("BudgetTransaction", back_populates="family", cascade="all, delete-orphan")
    budget_sync_state = relationship("BudgetSyncState", back_populates="family", uselist=False, cascade="all, delete-orphan")
    budget_categorization_rules = relationship("BudgetCategorizationRule", back_populates="family", cascade="all, delete-orphan")
    budget_goals = relationship("BudgetGoal", back_populates="family", cascade="all, delete-orphan")
    budget_recurring_transactions = relationship("BudgetRecurringTransaction", back_populates="family", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Family(id={self.id}, name={self.name})>"
