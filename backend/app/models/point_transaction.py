"""
PointTransaction model

Tracks all point-related activities for audit and transparency.
"""
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Enum as SQLEnum, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
import enum

from app.core.database import Base


class TransactionType(str, enum.Enum):
    """Types of point transactions"""
    TASK_COMPLETED = "task_completed"  # Points earned from task
    REWARD_REDEEMED = "reward_redeemed"  # Points spent on reward
    PARENT_ADJUSTMENT = "parent_adjustment"  # Manual adjustment by parent
    BONUS = "bonus"  # Bonus points
    PENALTY = "penalty"  # Point deduction
    TRANSFER = "transfer"  # Transfer between users


class PointTransaction(Base):
    """Point transaction log for transparency and audit"""
    
    __tablename__ = "point_transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    
    # Transaction details
    type = Column(SQLEnum(TransactionType), nullable=False, index=True)
    points = Column(Integer, nullable=False)  # Positive for earned, negative for spent
    description = Column(Text, nullable=True)
    
    # User linkage
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Balance tracking
    balance_before = Column(Integer, nullable=False, default=0)
    balance_after = Column(Integer, nullable=False)
    
    # Related entities
    task_id = Column(UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)  # Legacy, to be removed
    assignment_id = Column(UUID(as_uuid=True), ForeignKey("task_assignments.id", ondelete="SET NULL"), nullable=True)
    reward_id = Column(UUID(as_uuid=True), ForeignKey("rewards.id", ondelete="SET NULL"), nullable=True)
    
    # Metadata
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False, index=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)  # Admin who created
    
    # Relationships
    user = relationship("User", back_populates="point_transactions", foreign_keys=[user_id])
    task = relationship("Task", back_populates="point_transactions")  # Legacy
    assignment = relationship("TaskAssignment", back_populates="point_transactions")
    reward = relationship("Reward", back_populates="redemptions")
    created_by_user = relationship("User", foreign_keys=[created_by])

    def __repr__(self):
        return f"<PointTransaction(id={self.id}, type={self.type.value}, points={self.points})>"

    @classmethod
    def create_task_completion(cls, user_id: UUID, task_id: UUID, points: int, balance_before: int):
        """Create transaction for task completion (legacy)"""
        return cls(
            type=TransactionType.TASK_COMPLETED,
            user_id=user_id,
            task_id=task_id,
            points=points,
            balance_before=balance_before,
            balance_after=balance_before + points,
            description=f"Completed task and earned {points} points"
        )

    @classmethod
    def create_assignment_completion(cls, user_id: UUID, assignment_id: UUID, points: int, balance_before: int):
        """Create transaction for assignment completion"""
        return cls(
            type=TransactionType.TASK_COMPLETED,
            user_id=user_id,
            assignment_id=assignment_id,
            points=points,
            balance_before=balance_before,
            balance_after=balance_before + points,
            description=f"Completed task and earned {points} points"
        )

    @classmethod
    def create_reward_redemption(cls, user_id: UUID, reward_id: UUID, points_cost: int, balance_before: int):
        """Create transaction for reward redemption"""
        return cls(
            type=TransactionType.REWARD_REDEEMED,
            user_id=user_id,
            reward_id=reward_id,
            points=-points_cost,
            balance_before=balance_before,
            balance_after=balance_before - points_cost,
            description=f"Redeemed reward for {points_cost} points"
        )

    @classmethod
    def create_parent_adjustment(cls, user_id: UUID, points: int, balance_before: int, reason: str, created_by: UUID):
        """Create transaction for manual parent adjustment"""
        return cls(
            type=TransactionType.PARENT_ADJUSTMENT,
            user_id=user_id,
            points=points,
            balance_before=balance_before,
            balance_after=balance_before + points,
            description=reason,
            created_by=created_by
        )
