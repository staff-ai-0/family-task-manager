"""
User Reward Goal model

Represents goals that users set to earn rewards through the economy loop.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class UserRewardGoal(Base):
    __tablename__ = "user_reward_goals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
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
    reward_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rewards.id", ondelete="CASCADE"),
        nullable=False,
    )
    set_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    achieved_at = Column(DateTime(timezone=True), nullable=True)
    nudge_sent_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", foreign_keys=[user_id])
    reward = relationship("Reward")

    __table_args__ = (
        Index(
            "ix_user_reward_goals_user_active",
            "user_id",
            unique=True,
            postgresql_where=text("achieved_at IS NULL"),
        ),
    )
