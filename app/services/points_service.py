"""
Points Service

Business logic for point transaction management.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, or_
from typing import List, Optional
from datetime import datetime, timedelta
from uuid import UUID

from app.models import PointTransaction, User
from app.models.point_transaction import TransactionType
from app.schemas.points import ParentAdjustment, PointTransfer
from app.core.exceptions import (
    NotFoundException,
    ValidationException,
    ForbiddenException,
)
from app.services.base_service import verify_user_in_family, get_user_by_id


class PointsService:
    """Service for point-related operations"""

    @staticmethod
    async def get_user_balance(db: AsyncSession, user_id: UUID) -> int:
        """Get current point balance for a user"""
        user = await get_user_by_id(db, user_id)
        return user.points

    @staticmethod
    async def get_transaction_history(
        db: AsyncSession,
        user_id: UUID,
        limit: int = 50,
        transaction_type: Optional[TransactionType] = None,
    ) -> List[PointTransaction]:
        """Get transaction history for a user"""
        query = select(PointTransaction).where(PointTransaction.user_id == user_id)

        if transaction_type:
            query = query.where(PointTransaction.type == transaction_type)

        query = query.order_by(PointTransaction.created_at.desc()).limit(limit)
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def create_parent_adjustment(
        db: AsyncSession,
        adjustment: ParentAdjustment,
        parent_id: UUID,
        family_id: UUID,
    ) -> PointTransaction:
        """Create manual point adjustment by parent"""
        # Verify user exists and belongs to family
        user = await verify_user_in_family(db, adjustment.user_id, family_id)

        # Verify parent belongs to family
        await verify_user_in_family(db, parent_id, family_id)

        # Create transaction
        transaction = PointTransaction.create_parent_adjustment(
            user_id=adjustment.user_id,
            points=adjustment.points,
            balance_before=user.points,
            reason=adjustment.reason,
            created_by=parent_id,
        )

        # Update user balance
        user.points += adjustment.points
        if user.points < 0:
            user.points = 0  # Prevent negative balance

        db.add(transaction)
        await db.commit()
        await db.refresh(transaction)

        return transaction

    @staticmethod
    async def transfer_points(
        db: AsyncSession,
        transfer: PointTransfer,
        family_id: UUID,
    ) -> tuple[PointTransaction, PointTransaction]:
        """Transfer points between users (parent feature)"""
        # Verify both users exist and belong to family
        from_user = await verify_user_in_family(db, transfer.from_user_id, family_id)
        to_user = await verify_user_in_family(db, transfer.to_user_id, family_id)

        # Check if from_user has enough points
        if from_user.points < transfer.points:
            raise ValidationException(
                f"Insufficient points to transfer. User has {from_user.points} points"
            )

        # Create transactions
        reason = transfer.reason or "Point transfer"

        debit_transaction = PointTransaction(
            type=TransactionType.TRANSFER,
            user_id=transfer.from_user_id,
            points=-transfer.points,
            balance_before=from_user.points,
            balance_after=from_user.points - transfer.points,
            description=f"Transferred {transfer.points} points to {to_user.name}. {reason}",
        )

        credit_transaction = PointTransaction(
            type=TransactionType.TRANSFER,
            user_id=transfer.to_user_id,
            points=transfer.points,
            balance_before=to_user.points,
            balance_after=to_user.points + transfer.points,
            description=f"Received {transfer.points} points from {from_user.name}. {reason}",
        )

        # Update balances
        from_user.points -= transfer.points
        to_user.points += transfer.points

        db.add(debit_transaction)
        db.add(credit_transaction)
        await db.commit()
        await db.refresh(debit_transaction)
        await db.refresh(credit_transaction)

        return (debit_transaction, credit_transaction)

    @staticmethod
    async def get_total_earned(db: AsyncSession, user_id: UUID) -> int:
        """Get total points earned by user (all positive transactions)"""
        query = select(func.sum(PointTransaction.points)).where(
            and_(
                PointTransaction.user_id == user_id,
                PointTransaction.points > 0,
            )
        )
        result = await db.execute(query)
        return result.scalar() or 0

    @staticmethod
    async def get_total_spent(db: AsyncSession, user_id: UUID) -> int:
        """Get total points spent by user (all negative transactions)"""
        query = select(func.sum(PointTransaction.points)).where(
            and_(
                PointTransaction.user_id == user_id,
                PointTransaction.points < 0,
            )
        )
        result = await db.execute(query)
        return abs(result.scalar() or 0)

    @staticmethod
    async def get_points_summary(db: AsyncSession, user_id: UUID) -> dict:
        """Get comprehensive points summary for user"""
        user = await get_user_by_id(db, user_id)

        total_earned = await PointsService.get_total_earned(db, user_id)
        total_spent = await PointsService.get_total_spent(db, user_id)
        recent_transactions = await PointsService.get_transaction_history(
            db, user_id, limit=10
        )

        return {
            "user_id": user_id,
            "current_balance": user.points,
            "total_earned": total_earned,
            "total_spent": total_spent,
            "recent_transactions": recent_transactions,
        }
