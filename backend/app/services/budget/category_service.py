"""
Category Service

Business logic for budget category groups and categories.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from typing import List, Optional
from uuid import UUID

from app.models.budget import BudgetCategoryGroup, BudgetCategory
from app.schemas.budget import (
    CategoryGroupCreate,
    CategoryGroupUpdate,
    CategoryCreate,
    CategoryUpdate,
)
from app.services.base_service import BaseFamilyService
from app.core.exceptions import NotFoundException


class CategoryGroupService(BaseFamilyService[BudgetCategoryGroup]):
    """Service for budget category group operations"""

    model = BudgetCategoryGroup

    @classmethod
    async def create(
        cls,
        db: AsyncSession,
        family_id: UUID,
        data: CategoryGroupCreate,
    ) -> BudgetCategoryGroup:
        """
        Create a new category group.

        Args:
            db: Database session
            family_id: Family ID
            data: Category group creation data

        Returns:
            Created category group
        """
        group = BudgetCategoryGroup(
            family_id=family_id,
            name=data.name,
            sort_order=data.sort_order,
            is_income=data.is_income,
            hidden=data.hidden,
        )

        db.add(group)
        await db.commit()
        await db.refresh(group)
        return group

    @classmethod
    async def update(
        cls,
        db: AsyncSession,
        group_id: UUID,
        family_id: UUID,
        data: CategoryGroupUpdate,
    ) -> BudgetCategoryGroup:
        """
        Update a category group.

        Args:
            db: Database session
            group_id: Group ID to update
            family_id: Family ID for verification
            data: Update data

        Returns:
            Updated category group

        Raises:
            NotFoundException: If group not found
        """
        # Only include non-None values in update
        update_data = data.model_dump(exclude_unset=True)
        return await cls.update_by_id(db, group_id, family_id, update_data)

    @classmethod
    async def list_with_categories(
        cls,
        db: AsyncSession,
        family_id: UUID,
        include_hidden: bool = False,
    ) -> List[BudgetCategoryGroup]:
        """
        List all category groups with their categories.

        Args:
            db: Database session
            family_id: Family ID
            include_hidden: Whether to include hidden groups/categories

        Returns:
            List of category groups with categories loaded
        """
        from sqlalchemy.orm import selectinload

        query = (
            select(BudgetCategoryGroup)
            .where(BudgetCategoryGroup.family_id == family_id)
            .options(selectinload(BudgetCategoryGroup.categories))
            .order_by(BudgetCategoryGroup.sort_order, BudgetCategoryGroup.name)
        )

        if not include_hidden:
            query = query.where(BudgetCategoryGroup.hidden == False)

        result = await db.execute(query)
        groups = list(result.scalars().all())

        # Filter hidden categories if needed
        if not include_hidden:
            for group in groups:
                group.categories = [c for c in group.categories if not c.hidden]

        return groups


class CategoryService(BaseFamilyService[BudgetCategory]):
    """Service for budget category operations"""

    model = BudgetCategory

    @classmethod
    async def create(
        cls,
        db: AsyncSession,
        family_id: UUID,
        data: CategoryCreate,
    ) -> BudgetCategory:
        """
        Create a new category.

        Args:
            db: Database session
            family_id: Family ID
            data: Category creation data

        Returns:
            Created category

        Raises:
            NotFoundException: If category group not found
        """
        # Verify the group exists and belongs to the family
        group = await CategoryGroupService.get_by_id(db, data.group_id, family_id)

        category = BudgetCategory(
            family_id=family_id,
            group_id=data.group_id,
            name=data.name,
            sort_order=data.sort_order,
            hidden=data.hidden,
            rollover_enabled=data.rollover_enabled,
            goal_amount=data.goal_amount,
        )

        db.add(category)
        await db.commit()
        await db.refresh(category)
        return category

    @classmethod
    async def update(
        cls,
        db: AsyncSession,
        category_id: UUID,
        family_id: UUID,
        data: CategoryUpdate,
    ) -> BudgetCategory:
        """
        Update a category.

        Args:
            db: Database session
            category_id: Category ID to update
            family_id: Family ID for verification
            data: Update data

        Returns:
            Updated category

        Raises:
            NotFoundException: If category not found or group not found
        """
        # Verify new group if provided
        update_data = data.model_dump(exclude_unset=True)
        if "group_id" in update_data:
            await CategoryGroupService.get_by_id(db, update_data["group_id"], family_id)

        return await cls.update_by_id(db, category_id, family_id, update_data)

    @classmethod
    async def list_by_group(
        cls,
        db: AsyncSession,
        group_id: UUID,
        family_id: UUID,
        include_hidden: bool = False,
    ) -> List[BudgetCategory]:
        """
        List all categories in a group.

        Args:
            db: Database session
            group_id: Group ID to filter by
            family_id: Family ID for verification
            include_hidden: Whether to include hidden categories

        Returns:
            List of categories

        Raises:
            NotFoundException: If group not found
        """
        # Verify group exists
        await CategoryGroupService.get_by_id(db, group_id, family_id)

        query = (
            select(BudgetCategory)
            .where(
                and_(
                    BudgetCategory.family_id == family_id,
                    BudgetCategory.group_id == group_id,
                )
            )
            .order_by(BudgetCategory.sort_order, BudgetCategory.name)
        )

        if not include_hidden:
            query = query.where(BudgetCategory.hidden == False)

        result = await db.execute(query)
        return list(result.scalars().all())

    @classmethod
    async def get_with_group(
        cls,
        db: AsyncSession,
        category_id: UUID,
        family_id: UUID,
    ) -> BudgetCategory:
        """
        Get a category with its group loaded.

        Args:
            db: Database session
            category_id: Category ID
            family_id: Family ID for verification

        Returns:
            Category with group relationship loaded

        Raises:
            NotFoundException: If category not found
        """
        from sqlalchemy.orm import selectinload

        query = (
            select(BudgetCategory)
            .where(
                and_(
                    BudgetCategory.id == category_id,
                    BudgetCategory.family_id == family_id,
                )
            )
            .options(selectinload(BudgetCategory.group))
        )

        result = await db.execute(query)
        category = result.scalar_one_or_none()

        if not category:
            raise NotFoundException("Category not found")

        return category
