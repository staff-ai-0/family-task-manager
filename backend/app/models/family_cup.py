"""Family Cup season winner (P2 — weekly leaderboard seasons).

One row per (family, week_start). Persists the winner of a *closed* weekly
Family Cup season so past seasons survive even though the current-week ledger
window rolls over every Monday. Denormalizes the winner's name + points so the
record stays readable even after the user is deleted.

The live leaderboard is a family-scoped query over ``point_transactions`` in the
current Mon-Sun window (see FamilyCupService.weekly_leaderboard); this table is
history only.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class FamilyCupSeason(Base):
    __tablename__ = "family_cup_seasons"
    __table_args__ = (
        UniqueConstraint(
            "family_id", "week_start", name="uq_family_cup_family_week"
        ),
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
    # Monday of the season (family-local week).
    week_start = Column(Date, nullable=False)
    # SET NULL (not CASCADE): a deleted winner must not erase the season record —
    # winner_name keeps it readable.
    winner_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    winner_name = Column(String(120), nullable=True)  # denormalized snapshot
    winner_points = Column(Integer, nullable=False, default=0)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
