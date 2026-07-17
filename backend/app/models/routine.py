"""Routine models — icon tap-through routines for pre-readers.

Family-command-center staple (Skylight / Hearth): a parent authors a named
routine (morning / evening / custom) as an ordered list of big-icon steps a
young, non-reading kid taps through one by one. Completing the FULL routine
awards POINTS (privileges currency — never cash, per the two-currency rule)
and feeds the virtual pet via the existing PetService hook. Partial completion
awards nothing.

Three tables (one migration):

- ``Routine``          — parent-authored, family-scoped, per-kid or family-wide.
- ``RoutineStep``      — ordered step (bilingual label + emoji/icon).
- ``RoutineProgress``  — per (routine, user, local-day) tap state: the set of
                         completed step ids + a one-shot ``awarded`` guard so
                         the points/pet reward fires exactly once per day even
                         if steps are re-tapped or the routine is edited.

Multi-tenant: every row reaches ``families.id`` (Routine directly; Step and
Progress through their routine). Every service query filters by family_id.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


# Time-of-day windows a routine belongs to. Pure grouping/sorting hint for the
# kid + kiosk UI — no scheduling logic is attached (a routine is always
# available; the window just buckets it).
TIME_OF_DAY_VALUES = ("morning", "evening", "custom")

TIME_OF_DAY_LABELS = {
    "morning": {"es": "Mañana", "en": "Morning"},
    "evening": {"es": "Noche", "en": "Evening"},
    "custom": {"es": "Personalizada", "en": "Anytime"},
}


class Routine(Base):
    """A parent-authored, ordered icon routine for a kid (or the whole family)."""

    __tablename__ = "routines"
    __table_args__ = (
        CheckConstraint(
            "time_of_day IN ('morning', 'evening', 'custom')",
            name="chk_routine_time_of_day",
        ),
        CheckConstraint("points_reward >= 0", name="chk_routine_points_reward"),
    )

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    family_id = Column(
        UUID(as_uuid=True),
        ForeignKey("families.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Bilingual name (Mexico-first: `name` is the EN/default; `name_es` the ES).
    name = Column(String(120), nullable=False)
    name_es = Column(String(120), nullable=True)

    # Big emoji/icon shown on the routine tile.
    icon = Column(String(16), nullable=False, default="🌅", server_default="🌅")

    # Optional per-kid hex color for kiosk rendering (e.g. "#4FB8E6"). Null =
    # the UI derives one from the assigned kid (member palette).
    color = Column(String(9), nullable=True)

    # Grouping window (morning / evening / custom). See TIME_OF_DAY_VALUES.
    time_of_day = Column(
        String(16), nullable=False, default="morning", server_default="morning"
    )

    # Per-kid assignment. NULL = family-wide (every member runs their own copy,
    # each with independent daily progress + reward).
    assigned_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # POINTS (privileges) awarded once the kid completes EVERY step. Never cash.
    points_reward = Column(
        Integer, nullable=False, default=10, server_default="10"
    )

    # Ordering among routines within a time-of-day window.
    sort_order = Column(Integer, nullable=False, default=0, server_default="0")

    is_active = Column(
        Boolean, nullable=False, default=True, server_default="true", index=True
    )

    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    steps = relationship(
        "RoutineStep",
        back_populates="routine",
        cascade="all, delete-orphan",
        order_by="RoutineStep.sort_order",
    )
    assigned_user = relationship("User", foreign_keys=[assigned_user_id])

    def __repr__(self) -> str:
        return f"<Routine(id={self.id}, name={self.name!r}, tod={self.time_of_day})>"


class RoutineStep(Base):
    """One ordered step in a routine — a big icon + a short bilingual label."""

    __tablename__ = "routine_steps"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    routine_id = Column(
        UUID(as_uuid=True),
        ForeignKey("routines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    label = Column(String(120), nullable=False)
    label_es = Column(String(120), nullable=True)

    # Emoji/icon a non-reading kid recognizes (brush, plate, shirt, ...).
    icon = Column(String(16), nullable=False, default="✅", server_default="✅")

    sort_order = Column(Integer, nullable=False, default=0, server_default="0")

    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    routine = relationship("Routine", back_populates="steps")

    def __repr__(self) -> str:
        return f"<RoutineStep(id={self.id}, label={self.label!r}, order={self.sort_order})>"


class RoutineProgress(Base):
    """Per (routine, user, local-day) tap state + one-shot reward guard.

    ``completed_step_ids`` is the set (stored as a JSONB list of step-id
    strings) of steps the user has tapped done TODAY. ``awarded`` flips True the
    moment every current step is done and stays True for the day, so the
    points/pet reward is granted exactly once even across re-taps or a mid-day
    routine edit.
    """

    __tablename__ = "routine_progress"
    __table_args__ = (
        UniqueConstraint(
            "routine_id",
            "user_id",
            "completion_date",
            name="uq_routine_progress_day",
        ),
    )

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    routine_id = Column(
        UUID(as_uuid=True),
        ForeignKey("routines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    completion_date = Column(Date, nullable=False)

    completed_step_ids = Column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    awarded = Column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    points_awarded = Column(
        Integer, nullable=False, default=0, server_default="0"
    )
    pet_fed = Column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<RoutineProgress(routine={self.routine_id}, user={self.user_id}, "
            f"date={self.completion_date}, awarded={self.awarded})>"
        )
