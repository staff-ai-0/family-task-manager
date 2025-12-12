"""
Task model

Represents tasks (chores) that can be assigned to family members.
Tasks can be default (required) or extra (optional bonus tasks).
"""
from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
import enum

from app.core.database import Base


class TaskStatus(str, enum.Enum):
    """Task completion status"""
    PENDING = "pending"
    COMPLETED = "completed"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"


class TaskFrequency(str, enum.Enum):
    """Task recurrence frequency"""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    ONE_TIME = "one_time"


class Task(Base):
    """Task model for family chores and activities"""
    
    __tablename__ = "tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    title = Column(String(200), nullable=False)
    description = Column(String(1000), nullable=True)
    points = Column(Integer, nullable=False, default=10)  # Points awarded on completion
    
    # Task classification
    is_default = Column(Boolean, default=False, nullable=False)  # Required task vs optional
    frequency = Column(SQLEnum(TaskFrequency), default=TaskFrequency.DAILY, nullable=False)
    status = Column(SQLEnum(TaskStatus), default=TaskStatus.PENDING, nullable=False, index=True)
    
    # Assignment
    assigned_to = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    family_id = Column(UUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Scheduling
    due_date = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Consequence linkage
    consequence_id = Column(UUID(as_uuid=True), ForeignKey("consequences.id", ondelete="SET NULL"), nullable=True)
    
    # Metadata
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    assigned_user = relationship("User", back_populates="assigned_tasks", foreign_keys=[assigned_to])
    creator = relationship("User", back_populates="created_tasks", foreign_keys=[created_by])
    family = relationship("Family", back_populates="tasks")
    consequence = relationship("Consequence", back_populates="triggered_task", foreign_keys=[consequence_id])
    point_transactions = relationship("PointTransaction", back_populates="task", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Task(id={self.id}, title='{self.title}', status={self.status.value})>"

    @property
    def is_overdue(self) -> bool:
        """Check if task is past due date"""
        if self.due_date and self.status == TaskStatus.PENDING:
            return datetime.utcnow() > self.due_date
        return False

    @property
    def can_complete(self) -> bool:
        """Check if task can be marked as completed"""
        return self.status in [TaskStatus.PENDING, TaskStatus.OVERDUE]
