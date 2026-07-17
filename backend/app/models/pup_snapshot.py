"""PUP score snapshot (W6.3).

One row per (family, day). The daily scheduler writes today's snapshot;
upserts make a same-day re-run a no-op.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class PupScoreSnapshot(Base):
    __tablename__ = "pup_score_snapshots"
    __table_args__ = (
        UniqueConstraint("family_id", "snapshot_date", name="uq_pup_family_date"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    family_id = Column(
        UUID(as_uuid=True),
        ForeignKey("families.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    score = Column(Integer, nullable=False)
    label = Column(String(16), nullable=False)
    snapshot_date = Column(Date, nullable=False)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
