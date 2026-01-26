"""
Reward model

Represents rewards that can be redeemed with accumulated points.
"""
from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
import enum

from app.core.database import Base


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
