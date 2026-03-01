"""
Month Locking Service

Business logic for month closing/locking operations.
Prevents edits to past closed months for data integrity.
"""

from datetime import date, datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from typing import List, Optional
from uuid import UUID

from app.models.budget import BudgetAllocation
from app.services.base_service import BaseFamilyService
from app.core.exceptions import NotFoundException, ValidationError


class MonthLockingService(BaseFamilyService[BudgetAllocation]):
    """Service for month locking/closing operations"""

    model = BudgetAllocation

    @classmethod
    async def close_month(
        cls,
        db: AsyncSession,
        family_id: UUID,
        month: date,
    ) -> dict:
        """
        Close a month by setting closed_at on all allocations for that month.
        Prevents any modifications to transactions or allocations for closed months.

        Args:
            db: Database session
            family_id: Family ID
            month: Month to close (first day of month)

        Returns:
            Dictionary with closure details (allocation_count, closed_at)

        Raises:
            NotFoundException: If no allocations exist for the month
        """
        # Get all allocations for this family and month
        query = select(BudgetAllocation).where(
            and_(
                BudgetAllocation.family_id == family_id,
                BudgetAllocation.month == month,
            )
        )
        result = await db.execute(query)
        allocations = result.scalars().all()

        if not allocations:
            raise NotFoundException(
                f"No allocations found for family {family_id} in month {month}"
            )

        # Close all allocations for this month
        closed_at = datetime.utcnow()
        for allocation in allocations:
            allocation.closed_at = closed_at

        await db.commit()

        return {
            "allocation_count": len(allocations),
            "closed_at": closed_at,
            "month": month,
        }

    @classmethod
    async def reopen_month(
        cls,
        db: AsyncSession,
        family_id: UUID,
        month: date,
    ) -> dict:
        """
        Reopen a closed month by clearing closed_at on all allocations.
        Allows modifications to transactions and allocations again.

        Args:
            db: Database session
            family_id: Family ID
            month: Month to reopen (first day of month)

        Returns:
            Dictionary with reopen details (allocation_count)

        Raises:
            NotFoundException: If no closed allocations exist for the month
        """
        # Get all closed allocations for this family and month
        query = select(BudgetAllocation).where(
            and_(
                BudgetAllocation.family_id == family_id,
                BudgetAllocation.month == month,
                BudgetAllocation.closed_at.isnot(None),
            )
        )
        result = await db.execute(query)
        allocations = result.scalars().all()

        if not allocations:
            raise NotFoundException(
                f"No closed allocations found for family {family_id} in month {month}"
            )

        # Reopen all allocations for this month
        for allocation in allocations:
            allocation.closed_at = None

        await db.commit()

        return {
            "allocation_count": len(allocations),
            "month": month,
        }

    @classmethod
    async def is_month_closed(
        cls,
        db: AsyncSession,
        family_id: UUID,
        month: date,
    ) -> bool:
        """
        Check if a month is closed.

        Args:
            db: Database session
            family_id: Family ID
            month: Month to check (first day of month)

        Returns:
            True if month is closed, False otherwise
        """
        # Check if any allocation for this month is closed
        query = select(func.count(BudgetAllocation.id)).where(
            and_(
                BudgetAllocation.family_id == family_id,
                BudgetAllocation.month == month,
                BudgetAllocation.closed_at.isnot(None),
            )
        )
        result = await db.execute(query)
        closed_count = result.scalar() or 0

        # Get total count for this month
        total_query = select(func.count(BudgetAllocation.id)).where(
            and_(
                BudgetAllocation.family_id == family_id,
                BudgetAllocation.month == month,
            )
        )
        total_result = await db.execute(total_query)
        total_count = total_result.scalar() or 0

        # Month is closed if all allocations are closed
        return closed_count > 0 and closed_count == total_count

    @classmethod
    async def get_month_status(
        cls,
        db: AsyncSession,
        family_id: UUID,
        month: date,
    ) -> dict:
        """
        Get detailed status of a month.

        Args:
            db: Database session
            family_id: Family ID
            month: Month to check (first day of month)

        Returns:
            Dictionary with status details (is_closed, closed_at, allocation_count)
        """
        is_closed = await cls.is_month_closed(db, family_id, month)

        # Get closed_at value if closed
        closed_at = None
        if is_closed:
            query = select(BudgetAllocation.closed_at).where(
                and_(
                    BudgetAllocation.family_id == family_id,
                    BudgetAllocation.month == month,
                    BudgetAllocation.closed_at.isnot(None),
                )
            )
            result = await db.execute(query)
            closed_at = result.scalar_one_or_none()

        # Count allocations
        count_query = select(func.count(BudgetAllocation.id)).where(
            and_(
                BudgetAllocation.family_id == family_id,
                BudgetAllocation.month == month,
            )
        )
        count_result = await db.execute(count_query)
        allocation_count = count_result.scalar() or 0

        return {
            "is_closed": is_closed,
            "closed_at": closed_at,
            "allocation_count": allocation_count,
            "month": month,
        }

    @classmethod
    async def get_closed_months(
        cls,
        db: AsyncSession,
        family_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> List[dict]:
        """
        List all closed months for a family.

        Args:
            db: Database session
            family_id: Family ID
            limit: Maximum number of months to return
            offset: Number of months to skip

        Returns:
            List of closed month details (month, closed_at, allocation_count)
        """
        # Get distinct months that have closed allocations
        query = (
            select(
                BudgetAllocation.month,
                func.max(BudgetAllocation.closed_at).label("closed_at"),
                func.count(BudgetAllocation.id).label("allocation_count"),
            )
            .where(
                and_(
                    BudgetAllocation.family_id == family_id,
                    BudgetAllocation.closed_at.isnot(None),
                )
            )
            .group_by(BudgetAllocation.month)
            .order_by(BudgetAllocation.month.desc())
            .limit(limit)
            .offset(offset)
        )

        result = await db.execute(query)
        rows = result.all()

        return [
            {
                "month": row[0],
                "closed_at": row[1],
                "allocation_count": row[2],
            }
            for row in rows
        ]

    @classmethod
    async def validate_month_not_closed(
        cls,
        db: AsyncSession,
        family_id: UUID,
        month: date,
    ) -> None:
        """
        Validate that a month is not closed. Raises exception if closed.

        Args:
            db: Database session
            family_id: Family ID
            month: Month to validate (first day of month)

        Raises:
            ValidationError: If month is closed
        """
        is_closed = await cls.is_month_closed(db, family_id, month)
        if is_closed:
            raise ValidationError(
                f"Cannot modify allocations or transactions for closed month {month}"
            )
