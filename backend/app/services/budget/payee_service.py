"""
Payee Service

Business logic for budget payee operations.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.models.budget import BudgetPayee
from app.schemas.budget import PayeeCreate, PayeeUpdate
from app.services.base_service import BaseFamilyService


class PayeeService(BaseFamilyService[BudgetPayee]):
    """Service for budget payee operations"""

    model = BudgetPayee

    @classmethod
    async def create(
        cls,
        db: AsyncSession,
        family_id: UUID,
        data: PayeeCreate,
    ) -> BudgetPayee:
        """
        Create a new payee.

        Args:
            db: Database session
            family_id: Family ID
            data: Payee creation data

        Returns:
            Created payee
        """
        payee = BudgetPayee(
            family_id=family_id,
            name=data.name,
            notes=data.notes,
        )

        db.add(payee)
        await db.commit()
        await db.refresh(payee)
        return payee

    @classmethod
    async def update(
        cls,
        db: AsyncSession,
        payee_id: UUID,
        family_id: UUID,
        data: PayeeUpdate,
    ) -> BudgetPayee:
        """
        Update a payee.

        Args:
            db: Database session
            payee_id: Payee ID to update
            family_id: Family ID for verification
            data: Update data

        Returns:
            Updated payee
        """
        update_data = data.model_dump(exclude_unset=True)
        return await cls.update_by_id(db, payee_id, family_id, update_data)
