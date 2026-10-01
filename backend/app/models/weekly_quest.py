"""UX-D3: one row per kid per week — which quest they have, its goal, the
bonus it pays, and whether it was paid / seen. Progress is derived on read."""
import uuid

from sqlalchemy import CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class WeeklyQuest(Base):
    __tablename__ = "weekly_quests"
    __table_args__ = (
        UniqueConstraint("family_id", "user_id", "week_start", name="uq_weekly_quests_family_user_week"),
        CheckConstraint("target >= 1", name="ck_weekly_quests_target"),
        CheckConstraint("bonus_points >= 0", name="ck_weekly_quests_bonus"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    family_id = Column(
        UUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    week_start = Column(Date, nullable=False)          # the Monday (family timezone)
    quest = Column(String(32), nullable=False)         # catalog key, e.g. "on_time"
    target = Column(Integer, nullable=False)           # fixed at creation, never moves
    bonus_points = Column(Integer, nullable=False)     # family setting at creation
    created_at = Column(DateTime(timezone=True), nullable=False)
    rewarded_at = Column(DateTime(timezone=True), nullable=True)   # set when the bonus is paid
    seen_at = Column(DateTime(timezone=True), nullable=True)       # set when the kid saw the done moment

    def __repr__(self):
        return f"<WeeklyQuest(user_id={self.user_id}, week_start={self.week_start}, quest={self.quest})>"
