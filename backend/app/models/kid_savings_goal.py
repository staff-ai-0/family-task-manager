"""KidSavingsGoal model (P2) — a kid's named savings goal on the CASH ledger.

A kid can earmark toward one named goal (free text, e.g. "bici $2000") tracked
against their **Save-jar** balance in the Family Bank. This lives entirely on the
CASH currency (``kid_bank_accounts.save_cents`` / ``users.cash_cents``) — it does
NOT read, write, or convert POINTS. There is deliberately no ``reward_id`` or any
link to the points economy (see ``UserRewardGoal`` for the separate,
points-based reward goal). Keeping the two apart is a hard product constraint:
chores → points (privileges); only /gigs → cash (Family Bank jars).

Lifecycle (``status``):
    pending   — kid proposed the goal; awaits a parent's approval
    active    — parent-approved (or parent-created); counts as the kid's goal
    cancelled — abandoned / superseded (terminal)

"Reached" is DERIVED, never stored as a status: a goal is reached when the kid's
Save-jar balance ``>= target_cents``. ``reached_at`` only guards the one-time
"goal reached" celebration notification (idempotent), independent of status.

INVARIANT (v1): a kid may have at most ONE non-terminal goal — enforced by the
partial unique index ``ix_kid_savings_goals_active`` over ``user_id`` where
``status IN ('pending','active')`` and re-checked in the service.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


# Status values. 'reached' is intentionally NOT a status — reaching is derived
# from the Save-jar balance so the goal keeps tracking live.
GOAL_PENDING = "pending"
GOAL_ACTIVE = "active"
GOAL_CANCELLED = "cancelled"
GOAL_STATUSES = (GOAL_PENDING, GOAL_ACTIVE, GOAL_CANCELLED)
GOAL_OPEN_STATUSES = (GOAL_PENDING, GOAL_ACTIVE)  # the "1 active goal" window


class KidSavingsGoal(Base):
    """A kid's single named cash savings goal, tracked against the Save jar."""

    __tablename__ = "kid_savings_goals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    family_id = Column(
        UUID(as_uuid=True),
        ForeignKey("families.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Free-text name the kid saves toward (e.g. "bici", "Nintendo Switch").
    name = Column(String(80), nullable=False)
    # Optional decoration for the kid UI; defaults to a target emoji in the app.
    emoji = Column(String(8), nullable=True)
    # Cash target in centavos (MXN). Must be positive.
    target_cents = Column(Integer, nullable=False)

    status = Column(
        String(16), nullable=False, default=GOAL_ACTIVE, server_default=GOAL_ACTIVE
    )

    created_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # One-time celebration guard — stamped the first time the Save jar crosses
    # target while the goal is active. Not a lifecycle status.
    reached_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint("target_cents > 0", name="ck_kid_savings_goal_target_positive"),
        CheckConstraint(
            "status IN ('pending', 'active', 'cancelled')",
            name="ck_kid_savings_goal_status",
        ),
        # v1: at most one pending-or-active goal per kid.
        Index(
            "ix_kid_savings_goals_active",
            "user_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'active')"),
        ),
        # NB: the ``family_id`` btree index is produced by ``index=True`` on the
        # column above (name ``ix_kid_savings_goals_family_id``, matching the
        # migration's explicit op.create_index) — do NOT re-declare it here or
        # metadata.create_all emits a duplicate-index DDL.
    )

    def __repr__(self):
        return (
            f"<KidSavingsGoal(user_id={self.user_id}, name={self.name!r}, "
            f"target={self.target_cents}, status={self.status})>"
        )
