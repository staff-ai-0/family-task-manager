"""
Reward model

Represents rewards that can be redeemed with accumulated points.
"""
from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, Text, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
import enum

from app.core.database import Base


class RedemptionStatus(str, enum.Enum):
    """Lifecycle of a parent-approval-gated reward redemption."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class RewardCategory(str, enum.Enum):
    """Reward categories"""
    SCREEN_TIME = "screen_time"  # Extra TV/tablet/game time
    TREATS = "treats"  # Candy, snacks, desserts
    ACTIVITIES = "activities"  # Movies, outings, play dates
    PRIVILEGES = "privileges"  # Stay up late, choose dinner
    MONEY = "money"  # Allowance, cash rewards
    TOYS = "toys"  # Small toys or items


class Reward(Base):
    """Reward model for points redemption"""
    
    __tablename__ = "rewards"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    title = Column(String(200), nullable=False)
    description = Column(String(1000), nullable=True)
    points_cost = Column(Integer, nullable=False)  # Points required to redeem
    
    # Classification
    category = Column(SQLEnum(RewardCategory), nullable=False, index=True)
    
    # Availability
    is_active = Column(Boolean, default=True, nullable=False)  # Can be temporarily disabled
    is_default = Column(Boolean, default=False, nullable=False)  # Default vs extra rewards
    requires_parent_approval = Column(Boolean, default=False, nullable=False)  # High-value rewards
    
    # Family isolation
    family_id = Column(UUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Display
    icon = Column(String(50), nullable=True)  # Icon identifier (emoji or icon class)
    
    # Metadata
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    family = relationship("Family", back_populates="rewards")
    redemptions = relationship("PointTransaction", back_populates="reward", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Reward(id={self.id}, title='{self.title}', cost={self.points_cost})>"

    @property
    def is_redeemable(self) -> bool:
        """Check if reward is currently available for redemption"""
        return self.is_active


class RewardRedemption(Base):
    """A redemption request for a reward that requires parent approval.

    High-value rewards (`Reward.requires_parent_approval`) don't deduct points
    immediately — they queue here as PENDING until a parent approves (points
    deducted then) or rejects (no deduction). Rewards without the flag skip
    this table entirely and deduct on the spot.
    """

    __tablename__ = "reward_redemptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    # Keep the row if the reward is later deleted; the snapshot preserves history.
    reward_id = Column(UUID(as_uuid=True), ForeignKey("rewards.id", ondelete="SET NULL"), nullable=True)
    reward_title = Column(String(200), nullable=False)
    points_cost = Column(Integer, nullable=False)

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    family_id = Column(UUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True)

    status = Column(String(16), default=RedemptionStatus.PENDING.value, nullable=False, index=True)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    decided_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    decision_notes = Column(Text, nullable=True)
    # Set when approved — links to the resulting point deduction.
    transaction_id = Column(UUID(as_uuid=True), ForeignKey("point_transactions.id", ondelete="SET NULL"), nullable=True)

    def __repr__(self):
        return f"<RewardRedemption(id={self.id}, status={self.status}, cost={self.points_cost})>"
