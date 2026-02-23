"""
Consequence model

Represents penalties/restrictions triggered when default tasks are not completed.
"""
from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, Enum as SQLEnum, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime, timedelta
import uuid
import enum

from app.core.database import Base


class ConsequenceSeverity(str, enum.Enum):
    """Severity levels for consequences"""
    LOW = "low"  # Minor restriction (1-2 days)
    MEDIUM = "medium"  # Moderate restriction (3-5 days)
    HIGH = "high"  # Severe restriction (7+ days)


class RestrictionType(str, enum.Enum):
    """Types of restrictions that can be applied"""
    SCREEN_TIME = "screen_time"  # No TV/tablet/games
    REWARDS = "rewards"  # Cannot redeem rewards
    EXTRA_TASKS = "extra_tasks"  # Cannot do extra tasks for points
    ALLOWANCE = "allowance"  # Reduced or no allowance
    ACTIVITIES = "activities"  # No recreational activities
    CUSTOM = "custom"  # Parent-defined restriction


class Consequence(Base):
    """Consequence model for task non-completion penalties"""
    
    __tablename__ = "consequences"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    
    # Severity and type
    severity = Column(SQLEnum(ConsequenceSeverity), nullable=False, default=ConsequenceSeverity.LOW)
    restriction_type = Column(SQLEnum(RestrictionType), nullable=False)
    
    # Duration
    duration_days = Column(Integer, nullable=False, default=1)
    
    # Status
    active = Column(Boolean, default=True, nullable=False, index=True)
    resolved = Column(Boolean, default=False, nullable=False)
    
    # Linkage
    triggered_by_task_id = Column(UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)  # Legacy
    triggered_by_assignment_id = Column(UUID(as_uuid=True), ForeignKey("task_assignments.id", ondelete="SET NULL"), nullable=True)
    applied_to_user = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    family_id = Column(UUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Dates
    start_date = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    end_date = Column(DateTime(timezone=True), nullable=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    
    # Metadata
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    triggered_task = relationship("Task", back_populates="consequence", foreign_keys=[triggered_by_task_id])  # Legacy
    triggered_assignment = relationship("TaskAssignment", back_populates="consequence", foreign_keys=[triggered_by_assignment_id])
    user = relationship("User", back_populates="consequences", foreign_keys=[applied_to_user])
    family = relationship("Family", back_populates="consequences")

    def __repr__(self):
        return f"<Consequence(id={self.id}, type={self.restriction_type.value}, active={self.active})>"

    @property
    def is_expired(self) -> bool:
        """Check if consequence has expired"""
        return datetime.utcnow() > self.end_date

    @property
    def days_remaining(self) -> int:
        """Calculate days remaining in consequence"""
        if self.resolved or self.is_expired:
            return 0
        delta = self.end_date - datetime.utcnow()
        return max(0, delta.days)

    def apply_consequence(self) -> None:
        """Apply consequence with calculated end date"""
        self.active = True
        self.start_date = datetime.utcnow()
        self.end_date = self.start_date + timedelta(days=self.duration_days)

    def resolve_consequence(self) -> None:
        """Mark consequence as resolved"""
        self.active = False
        self.resolved = True
        self.resolved_at = datetime.utcnow()
