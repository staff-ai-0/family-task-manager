"""
Saved Filter Service

CRUD operations for saved transaction filter presets.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import BudgetSavedFilter
from app.schemas.budget import SavedFilterCreate, SavedFilterUpdate
from app.services.base_service import BaseFamilyService


class SavedFilterService(BaseFamilyService[BudgetSavedFilter]):
    """Service for saved transaction filter operations."""

    model = BudgetSavedFilter

    @classmethod
    async def create(
        cls,
        db: AsyncSession,
        family_id: UUID,
        created_by: UUID,
        data: SavedFilterCreate,
    ) -> BudgetSavedFilter:
        """Create a new saved filter."""
        saved_filter = BudgetSavedFilter(
            family_id=family_id,
            name=data.name,
            conditions=data.conditions,
            conditions_op=data.conditions_op,
            created_by=created_by,
        )
        db.add(saved_filter)
        await db.commit()
        await db.refresh(saved_filter)
        return saved_filter

    @classmethod
    async def update(
        cls,
        db: AsyncSession,
        filter_id: UUID,
        family_id: UUID,
        data: SavedFilterUpdate,
    ) -> BudgetSavedFilter:
        """Update a saved filter."""
        update_data = data.model_dump(exclude_unset=True)
        return await cls.update_by_id(db, filter_id, family_id, update_data)
