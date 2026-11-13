"""
TaskAssignment model

Represents a specific instance of a task assigned to a family member.
Generated weekly by the shuffle algorithm from TaskTemplates.
Each assignment has a specific date and tracks completion status.
"""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    String,
    DateTime,
    Date,
    Float,
    Integer,
    ForeignKey,
    Index,
    SmallInteger,
    Text,
    Enum as SQLEnum,
)
from sqlalchemy import false
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import uuid
import enum

from app.core.database import Base


class AssignmentStatus(str, enum.Enum):
    """Assignment completion status"""

    PENDING = "pending"
    CLAIMED = "claimed"
    COMPLETED = "completed"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"
    TAKEN = "taken"  # Early Bird: the original owner lost it to someone who took it


# A row nobody still has to do: waived (CANCELLED) or handed over (TAKEN — the
# taker's own row carries the chore). Neither "to do" nor "done", so to-do
# counters and lists leave them out. Ledger-style readers that must still see
# a taken chore as the owner's loss (paycheck units, streak, pings) test TAKEN
# themselves on purpose.
CLOSED_STATUSES = (AssignmentStatus.CANCELLED, AssignmentStatus.TAKEN)


class ApprovalStatus(str, enum.Enum):
    """Gig approval lifecycle."""
    NONE = "none"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class TaskAssignment(Base):
    """Specific task instance assigned to a user for a given date"""

    __tablename__ = "task_assignments"

    # Hot path: due/overdue sweeps + kid due-today lists filter family_id and
    # then range/order on assigned_date (due_date is only the optional
    # intra-day deadline — the old (family_id, due_date) index sat on a column
    # nothing queried). Mirrors the task_forensic_fixes migration.
    __table_args__ = (
        Index("ix_task_assignments_family_assigned", "family_id", "assigned_date"),
        CheckConstraint(
            "completion_grade IN ('full','partial','missed')",
            name="ck_task_assignments_completion_grade",
        ),
        CheckConstraint(
            "partial_credit_pct >= 0 AND partial_credit_pct <= 100",
            name="ck_task_assignments_partial_credit_pct",
        ),
    )

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
        SQLEnum(
            AssignmentStatus,
            values_callable=lambda x: [e.value for e in x],
        ),
        default=AssignmentStatus.PENDING,
        nullable=False,
        index=True,
    )

    approval_status = Column(
        SQLEnum(
            ApprovalStatus,
            values_callable=lambda x: [e.value for e in x],
            name="approval_status",
        ),
        nullable=False,
        default=ApprovalStatus.NONE,
        server_default="none",
        index=True,
    )
    # Grading at parent review: 'full' (100%), 'partial' (partial_credit_pct),
    # 'missed' (0). NULL = decided pre-feature or via legacy plain reject.
    completion_grade = Column(String(10), nullable=True)
    partial_credit_pct = Column(SmallInteger, nullable=True)

    proof_text = Column(Text, nullable=True)
    proof_image_url = Column(String(512), nullable=True)
    ai_validation_score = Column(Float, nullable=True)
    ai_validation_notes = Column(Text, nullable=True)
    approved_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    approved_at = Column(DateTime(timezone=True), nullable=True)
    approval_notes = Column(Text, nullable=True)

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
    # True when a parent recorded the completion retroactively
    # (mark_done_for_kid); such a row counts as done whatever completed_at says.
    marked_done_by_parent = Column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    claimed_at = Column(DateTime(timezone=True), nullable=True)

    # Early Bird take-over: the new assignment points at the one it replaced
    # (taken_from_id); the replaced row records who took it (taken_by/taken_at).
    taken_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    taken_at = Column(DateTime(timezone=True), nullable=True)
    taken_from_id = Column(
        UUID(as_uuid=True),
        ForeignKey("task_assignments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    early_bonus_points = Column(Integer, nullable=True)

    # Metadata
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
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
            return datetime.now(timezone.utc) > self.due_date
        return False

    @property
    def can_complete(self) -> bool:
        """Check if assignment can be marked as completed"""
        return self.status in [
            AssignmentStatus.PENDING,
            AssignmentStatus.CLAIMED,
            AssignmentStatus.OVERDUE,
        ]

    @property
    def can_claim(self) -> bool:
        """Only PENDING gigs are claimable (mandatory has no claim semantic)."""
        return self.status == AssignmentStatus.PENDING
