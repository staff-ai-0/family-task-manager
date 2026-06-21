"""
TaskTemplate model

Represents reusable task/chore definitions that can be assigned weekly.
Templates are permanent and family-scoped. They define WHAT needs to be done,
while TaskAssignment defines WHO does it and WHEN.
"""

from sqlalchemy import (
    Column,
    String,
    Integer,
    Boolean,
    DateTime,
    ForeignKey,
    Text,
    CheckConstraint,
    Enum as SQLEnum,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
from enum import Enum
import uuid

from app.core.database import Base


class AssignmentType(str, Enum):
    """How the task should be assigned to family members"""
    AUTO = "auto"  # Automatic load balancing (default)
    FIXED = "fixed"  # Always assign to specific user(s)
    ROTATE = "rotate"  # Rotate among specific users in order


class GigMode(str, Enum):
    """How a gig (is_bonus=True) resolves when multiple members are eligible.

    - claim:         one assignment per member, first claimer locks it. (default)
    - rotation:      same as claim but assigned_user_ids cycle per week.
    - competition:   one assignment per member, first to CLAIM wins —
                     others' assignments auto-cancel.
    - collaboration: assignment is shared; N members must complete it
                     (collaboration_min_count). Points split equally.
    """
    CLAIM = "claim"
    ROTATION = "rotation"
    COMPETITION = "competition"
    COLLABORATION = "collaboration"


EFFORT_MULTIPLIERS: dict[int, float] = {1: 1.0, 2: 1.5, 3: 2.0}


class TaskTemplate(Base):
    """Reusable task template for weekly assignment generation"""

    __tablename__ = "task_templates"
    __table_args__ = (
        CheckConstraint(
            "is_bonus = true OR points = 0",
            name="chk_mandatory_zero_points",
        ),
        CheckConstraint(
            "effort_level BETWEEN 1 AND 3",
            name="chk_effort_level_range",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    title_es = Column(String(200), nullable=True)
    description_es = Column(Text, nullable=True)
    points = Column(Integer, nullable=False, default=10)
    effort_level = Column(Integer, nullable=False, default=1, server_default="1")

    # Auto late penalty (W1.2). When auto_late_penalty=True and an assignment
    # flips PENDING → OVERDUE during the family-tz daily sweep, a Consequence
    # row is auto-instantiated for the assigned user. restriction_type and
    # severity stored as raw strings to avoid a circular import with the
    # Consequence enums; values mirror RestrictionType / ConsequenceSeverity.
    auto_late_penalty = Column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    late_restriction_type = Column(String(32), nullable=True)
    late_severity = Column(String(16), nullable=True)
    late_duration_days = Column(
        Integer, nullable=False, default=1, server_default="1"
    )

    # Chore locking (W1.3). When True, any open assignment (PENDING/OVERDUE)
    # for this template will block reward redemption for the assigned user
    # until the assignment is completed or cancelled.
    blocks_rewards = Column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Gig resolution mode (W4.1). Only meaningful when is_bonus=True.
    gig_mode = Column(
        String(16), nullable=False, default=GigMode.CLAIM.value,
        server_default=GigMode.CLAIM.value,
    )
    collaboration_min_count = Column(
        Integer, nullable=False, default=2, server_default="2"
    )

    # Scheduling: how often per week (1=daily, 3=every 3 days, 7=weekly)
    interval_days = Column(Integer, nullable=False, default=1)

    # Assignment configuration
    assignment_type = Column(
        SQLEnum(AssignmentType, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=AssignmentType.AUTO,
        server_default="auto"
    )
    assigned_user_ids = Column(
        JSONB,
        nullable=True,
        comment="List of user UUIDs for FIXED or ROTATE assignment types"
    )
    allowed_roles = Column(
        JSONB,
        nullable=True,
        comment="List of role strings (parent/teen/child) eligible under AUTO. Null = all roles allowed."
    )

    # Classification
    is_bonus = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False, index=True)

    # Ownership
    created_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    family_id = Column(
        UUID(as_uuid=True),
        ForeignKey("families.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

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
    creator = relationship("User", back_populates="created_templates", foreign_keys=[created_by])
    family = relationship("Family", back_populates="task_templates")
    assignments = relationship(
        "TaskAssignment", back_populates="template", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<TaskTemplate(id={self.id}, title='{self.title}', interval={self.interval_days}d, bonus={self.is_bonus})>"

    @property
    def frequency_label(self) -> str:
        """Human-readable frequency label"""
        if self.interval_days == 1:
            return "daily"
        elif self.interval_days == 7:
            return "weekly"
        else:
            return f"every {self.interval_days} days"

    @property
    def effective_points(self) -> int:
        """Points after effort multiplier (1=×1.0, 2=×1.5, 3=×2.0)."""
        mult = EFFORT_MULTIPLIERS.get(self.effort_level or 1, 1.0)
        return int(round((self.points or 0) * mult))

    @property
    def award_points_per_completer(self) -> int:
        """Base (minimum) points credited to a single completer — the floor
        share for collaboration-mode gigs, full effective_points otherwise.

        This is the display value. The exact award per completer (which spreads
        the leftover so the shares sum to the pot) is `collaboration_share`.
        """
        if (self.gig_mode or "claim") == "collaboration":
            split = max(1, int(self.collaboration_min_count or 1))
            return self.effective_points // split
        return self.effective_points

    @staticmethod
    def distribute_points(pot: int, n: int) -> list[int]:
        """Split `pot` among `n` completers so the shares always sum to `pot`.

        Floor-divide, then hand the remainder to the first completers one point
        each — no points are silently lost (e.g. 10 over 3 -> [4, 3, 3]).
        """
        n = max(1, n)
        base, rem = divmod(max(0, pot), n)
        return [base + (1 if i < rem else 0) for i in range(n)]

    def collaboration_share(self, completer_index: int) -> int:
        """Exact points for the completer at 0-based approval order
        `completer_index`. For non-collaboration modes every completer earns
        the full effective_points."""
        if (self.gig_mode or "claim") != "collaboration":
            return self.effective_points
        split = max(1, int(self.collaboration_min_count or 1))
        base, rem = divmod(self.effective_points, split)
        return base + (1 if completer_index < rem else 0)
