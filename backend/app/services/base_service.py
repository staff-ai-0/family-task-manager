"""
Base Service Class

Provides common CRUD operations for family-scoped entities.
Reduces duplication across service classes.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, delete as sql_delete
from typing import TypeVar, Generic, Type, List, Optional
from uuid import UUID
from datetime import datetime

from app.core.exceptions import NotFoundException

# Import User model for helper methods
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models import User

# Generic type for SQLAlchemy models
ModelType = TypeVar("ModelType")


class BaseFamilyService(Generic[ModelType]):
    """
    Base service class for family-scoped entities.

    Provides common CRUD operations that work with any family-scoped model.
    Subclasses should set the `model` class attribute.

    Example:
        class TaskService(BaseFamilyService[Task]):
            model = Task
    """

    model: Type[ModelType] = None

    @classmethod
    async def get_by_id(
        cls,
        db: AsyncSession,
        entity_id: UUID,
        family_id: UUID,
    ) -> ModelType:
        """
        Get an entity by ID with family scope verification.

        Args:
            db: Database session
            entity_id: ID of the entity to retrieve
            family_id: Family ID for scope verification

        Returns:
            The entity instance

        Raises:
            NotFoundException: If entity not found or doesn't belong to family
        """
        if cls.model is None:
            raise NotImplementedError("Subclass must set 'model' class attribute")

        query = select(cls.model).where(
            and_(cls.model.id == entity_id, cls.model.family_id == family_id)
        )
        result = await db.execute(query)
        entity = result.scalar_one_or_none()

        if not entity:
            entity_name = cls.model.__name__
            raise NotFoundException(f"{entity_name} not found")

        return entity

    @classmethod
    async def list_by_family(
        cls,
        db: AsyncSession,
        family_id: UUID,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> List[ModelType]:
        """
        List all entities for a family.

        Args:
            db: Database session
            family_id: Family ID to filter by
            limit: Optional limit on number of results
            offset: Optional offset for pagination

        Returns:
            List of entity instances
        """
        if cls.model is None:
            raise NotImplementedError("Subclass must set 'model' class attribute")

        query = select(cls.model).where(cls.model.family_id == family_id)

        # Apply ordering if created_at exists
        if hasattr(cls.model, "created_at"):
            query = query.order_by(cls.model.created_at.desc())

        if limit:
            query = query.limit(limit)
        if offset:
            query = query.offset(offset)

        result = await db.execute(query)
        return list(result.scalars().all())

    @classmethod
    async def delete_by_id(
        cls,
        db: AsyncSession,
        entity_id: UUID,
        family_id: UUID,
    ) -> None:
        """
        Delete an entity by ID with family scope verification.

        Args:
            db: Database session
            entity_id: ID of the entity to delete
            family_id: Family ID for scope verification

        Raises:
            NotFoundException: If entity not found or doesn't belong to family
        """
        # First verify entity exists and belongs to family
        entity = await cls.get_by_id(db, entity_id, family_id)

        # Delete the entity
        await db.delete(entity)
        await db.commit()

    @classmethod
    async def update_by_id(
        cls,
        db: AsyncSession,
        entity_id: UUID,
        family_id: UUID,
        update_data: dict,
    ) -> ModelType:
        """
        Update an entity with provided data.

        Args:
            db: Database session
            entity_id: ID of the entity to update
            family_id: Family ID for scope verification
            update_data: Dictionary of fields to update

        Returns:
            Updated entity instance

        Raises:
            NotFoundException: If entity not found or doesn't belong to family
        """
        # Get entity with family scope verification
        entity = await cls.get_by_id(db, entity_id, family_id)

        # Update fields
        for field, value in update_data.items():
            if hasattr(entity, field):
                setattr(entity, field, value)

        # Update timestamp if exists
        if hasattr(entity, "updated_at"):
            entity.updated_at = datetime.utcnow()

        await db.commit()
        await db.refresh(entity)
        return entity

    @classmethod
    async def count_by_family(
        cls,
        db: AsyncSession,
        family_id: UUID,
    ) -> int:
        """
        Count entities for a family.

        Args:
            db: Database session
            family_id: Family ID to filter by

        Returns:
            Count of entities
        """
        if cls.model is None:
            raise NotImplementedError("Subclass must set 'model' class attribute")

        from sqlalchemy import func

        query = (
            select(func.count())
            .select_from(cls.model)
            .where(cls.model.family_id == family_id)
        )
        result = await db.execute(query)
        return result.scalar_one()


# Query Helper Functions (can be used by any service)


async def verify_user_in_family(
    db: AsyncSession, user_id: UUID, family_id: UUID
) -> "User":
    """
    Verify that a user exists and belongs to the specified family.

    Args:
        db: Database session
        user_id: ID of the user to verify
        family_id: Family ID to verify membership

    Returns:
        User instance

    Raises:
        NotFoundException: If user not found or doesn't belong to family
    """
    from app.models import User

    query = select(User).where(and_(User.id == user_id, User.family_id == family_id))
    user = (await db.execute(query)).scalar_one_or_none()

    if not user:
        raise NotFoundException("User not found or does not belong to this family")

    return user


async def get_user_by_id(db: AsyncSession, user_id: UUID) -> "User":
    """
    Get a user by ID.

    Args:
        db: Database session
        user_id: ID of the user to retrieve

    Returns:
        User instance

    Raises:
        NotFoundException: If user not found
    """
    from app.models import User

    query = select(User).where(User.id == user_id)
    user = (await db.execute(query)).scalar_one_or_none()

    if not user:
        raise NotFoundException("User not found")

    return user
