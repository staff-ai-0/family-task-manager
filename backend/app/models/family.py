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
    timezone = Column(String(64), nullable=False, default="UTC", server_default="UTC")
    created_by = Column(UUID(as_uuid=True), nullable=True)  # Nullable during creation, set after user created
    join_code = Column(String(10), unique=True, nullable=True, index=True)  # Short code for family invites
    # Stable public referral code for the give-a-month/get-a-month growth
    # loop. Distinct from join_code (kids join with join_code; this one is
    # shared publicly as https://…/register?ref=CODE). Nullable + generated
    # on demand (ReferralService.get_or_create_referral_code); existing rows
    # were backfilled by the referral_program migration.
    referral_code = Column(String(16), unique=True, nullable=True, index=True)
    # Internal referral credit expiry (give-a-month/get-a-month). While this
    # is in the future, premium.get_family_plan floors the family at Plus,
    # independent of any paid subscription. It lives HERE — on the family row,
    # NOT on the subscription's current_period_end — precisely so the nightly
    # PayPal reconcile sweep (which overwrites current_period_end from
    # PayPal's next_billing_at) can never erase the reward. NULL = no credit.
    referral_bonus_until = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    # Parental opt-in for AI processing of KID-generated content (gig proof
    # photos, Jarvis/MCP reads of family chat). False = those AI paths are
    # skipped (manual HITL flows instead). ai_processing_consent_at is stamped
    # when a parent decides either way; NULL = never asked (dashboard prompts).
    ai_processing_consent = Column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    ai_processing_consent_at = Column(DateTime, nullable=True)

    # Onboarding checklist — tracked per family, all False on creation.
    onboarding_child_invited = Column(Boolean, nullable=False, default=False, server_default="false")
    onboarding_task_created = Column(Boolean, nullable=False, default=False, server_default="false")
    onboarding_reward_created = Column(Boolean, nullable=False, default=False, server_default="false")
    onboarding_points_awarded = Column(Boolean, nullable=False, default=False, server_default="false")
    onboarding_dismissed = Column(Boolean, nullable=False, default=False, server_default="false")

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Soft-delete tombstone (self-serve account deletion). Set when a parent
    # closes the whole family; the row + all family data is retained for a
    # grace window (FamilyDeletionService.PURGE_RETENTION_DAYS) and only then
    # hard-purged by the daily purge sweep. A non-null value means the account
    # is closed — auth treats every member as gone (401 'account closed'), and
    # the family is excluded from join-by-code lookups. Indexed so the purge
    # sweep's `WHERE deleted_at < cutoff` is a cheap range scan.
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)

    # Relationships
    # delete-orphan so deleting a family cascades to its members (users have a
    # NOT NULL family_id and cannot be orphaned); each user in turn cascades to
    # its own owned rows (point_transactions, task_assignments, consequences…).
    members = relationship(
        "User", back_populates="family", cascade="all, delete-orphan"
    )
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
    budget_custom_reports = relationship("BudgetCustomReport", back_populates="family", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Family(id={self.id}, name={self.name})>"
