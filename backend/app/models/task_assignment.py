"""
TaskAssignment model

Represents a specific instance of a task assigned to a family member.
Generated weekly by the shuffle algorithm from TaskTemplates.
Each assignment has a specific date and tracks completion status.
"""

from sqlalchemy import (
    Column,
    String,
    Integer,
    Boolean,
    DateTime,
    Date,
    ForeignKey,
    Enum as SQLEnum,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime, date
import uuid
import enum

from app.core.database import Base


class AssignmentStatus(str, enum.Enum):
    """Assignment completion status"""

    PENDING = "pending"
    COMPLETED = "completed"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"


class TaskAssignment(Base):
    """Specific task instance assigned to a user for a given date"""

    __tablename__ = "task_assignments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    # Link to template
    template_id = Column(
        UUID(as_uuid=True),
        ForeignKey("task_templates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Assignment
    assigned_to = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    family_id = Column(
        UUID(as_uuid=True),
        ForeignKey("families.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Status
    status = Column(
        SQLEnum(AssignmentStatus),
        default=AssignmentStatus.PENDING,
        nullable=False,
        index=True,
    )

    # Scheduling
    assigned_date = Column(Date, nullable=False)  # The specific date this task is for
    due_date = Column(
        DateTime(timezone=True), nullable=True
    )  # Optional deadline within the day
    week_of = Column(
        Date, nullable=False, index=True
    )  # Monday of the week (for grouping)

    # Completion
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Metadata
    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # Relationships
    template = relationship("TaskTemplate", back_populates="assignments")
    assigned_user = relationship(
        "User", back_populates="task_assignments", foreign_keys=[assigned_to]
    )
    family = relationship("Family", back_populates="task_assignments")
    point_transactions = relationship(
        "PointTransaction", back_populates="assignment", cascade="all, delete-orphan"
    )
    consequence = relationship(
        "Consequence", back_populates="triggered_assignment", uselist=False
    )

    def __repr__(self):
        return (
            f"<TaskAssignment(id={self.id}, date={self.assigned_date}, "
            f"status={self.status.value})>"
        )

    @property
    def is_overdue(self) -> bool:
        """Check if assignment is past due date"""
        if self.due_date and self.status == AssignmentStatus.PENDING:
            return datetime.utcnow() > self.due_date
        return False

    @property
    def can_complete(self) -> bool:
        """Check if assignment can be marked as completed"""
        return self.status in [AssignmentStatus.PENDING, AssignmentStatus.OVERDUE]
