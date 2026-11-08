"""Early Bird settled week — one row per (teen, Mon–Sun week).

`result` is early / missed / neutral; `run_weeks` is the consecutive-early run
after that week (every 3rd pays `bonus_cents` once, `paid_at` marks it).
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class EarlyBirdWeek(Base):
    __tablename__ = "early_bird_weeks"
    __table_args__ = (
        UniqueConstraint("user_id", "week_of", name="uq_early_bird_weeks_user_week"),
        CheckConstraint("result IN ('early','missed','neutral')", name="ck_early_bird_weeks_result"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    family_id = Column(UUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    week_of = Column(Date, nullable=False)
    result = Column(String(10), nullable=False)
    run_weeks = Column(Integer, nullable=False)
    bonus_cents = Column(Integer, nullable=False, default=0, server_default="0")
    paid_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
