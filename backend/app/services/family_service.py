"""
Family Service

Business logic for family group management.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from typing import List, Optional
from datetime import datetime
from uuid import UUID

from app.models import Family, User, Task, Reward, Consequence
from app.models.task import TaskStatus
from app.models.family import generate_join_code
from app.schemas.family import FamilyCreate, FamilyUpdate
from app.core.exceptions import NotFoundException, ValidationException


class FamilyService:
    """Service for family-related operations"""

    @staticmethod
    async def create_family(
        db: AsyncSession,
        family_data: FamilyCreate,
        created_by: UUID,
    ) -> Family:
        """Create a new family"""
        family = Family(
            name=family_data.name,
            created_by=created_by,
            is_active=True,
        )
        
        db.add(family)
        await db.commit()
        await db.refresh(family)
        return family

    @staticmethod
    async def generate_join_code(db: AsyncSession, family_id: UUID) -> str:
        """Generate or regenerate a unique join code for a family"""
        family = await FamilyService.get_family(db, family_id)
        
        # Try up to 10 times to generate a unique code
        for _ in range(10):
            code = generate_join_code()
            existing = (await db.execute(
                select(Family).where(Family.join_code == code)
            )).scalar_one_or_none()
            if not existing:
                family.join_code = code
                family.updated_at = datetime.utcnow()
                await db.commit()
                await db.refresh(family)
                return code
        
        raise ValidationException("Could not generate unique join code. Try again.")

    @staticmethod
    async def get_family_by_join_code(db: AsyncSession, join_code: str) -> Optional[Family]:
        """Find a family by its join code"""
        family = (await db.execute(
            select(Family).where(
                Family.join_code == join_code.upper().strip(),
                Family.is_active == True,
            )
        )).scalar_one_or_none()
        return family

    @staticmethod
    async def get_family(db: AsyncSession, family_id: UUID) -> Family:
        """Get a family by ID"""
        family = (await db.execute(
            select(Family).where(Family.id == family_id)
        )).scalar_one_or_none()
        if not family:
            raise NotFoundException("Family not found")
        return family

    @staticmethod
    async def update_family(
        db: AsyncSession,
        family_id: UUID,
        family_data: FamilyUpdate,
    ) -> Family:
        """Update family details"""
        family = await FamilyService.get_family(db, family_id)
        
        # Update fields if provided
        update_fields = family_data.model_dump(exclude_unset=True)
        for field, value in update_fields.items():
            setattr(family, field, value)
        
        family.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(family)
        return family

    @staticmethod
    async def get_family_members(db: AsyncSession, family_id: UUID) -> List[User]:
        """Get all members of a family"""
        query = select(User).where(User.family_id == family_id).order_by(User.name)
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def get_family_stats(db: AsyncSession, family_id: UUID) -> dict:
        """Get comprehensive family statistics"""
        # Count members
        members_count = (await db.execute(
            select(func.count()).select_from(User).where(User.family_id == family_id)
        )).scalar()
        
        # Count tasks
        total_tasks = (await db.execute(
            select(func.count()).select_from(Task).where(Task.family_id == family_id)
        )).scalar()
        
        completed_tasks = (await db.execute(
            select(func.count()).select_from(Task).where(
                and_(Task.family_id == family_id, Task.status == TaskStatus.COMPLETED)
            )
        )).scalar()
        
        pending_tasks = (await db.execute(
            select(func.count()).select_from(Task).where(
                and_(Task.family_id == family_id, Task.status == TaskStatus.PENDING)
            )
        )).scalar()
        
        # Count rewards
        total_rewards = (await db.execute(
            select(func.count()).select_from(Reward).where(
                and_(Reward.family_id == family_id, Reward.is_active == True)
            )
        )).scalar()
        
        # Count active consequences
        active_consequences = (await db.execute(
            select(func.count()).select_from(Consequence).where(
                and_(
                    Consequence.family_id == family_id,
                    Consequence.active == True,
                    Consequence.resolved == False,
                )
            )
        )).scalar()
        
        return {
            "total_members": members_count or 0,
            "total_tasks": total_tasks or 0,
            "completed_tasks": completed_tasks or 0,
            "pending_tasks": pending_tasks or 0,
            "total_rewards": total_rewards or 0,
            "active_consequences": active_consequences or 0,
        }

    @staticmethod
    async def delete_family(db: AsyncSession, family_id: UUID) -> None:
        """Delete a family (with cascade to all related data)"""
        family = await FamilyService.get_family(db, family_id)
        await db.delete(family)
        await db.commit()
