"""
Consequence Service

Business logic for consequence management and enforcement.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from typing import List, Optional
from datetime import datetime
from uuid import UUID

from app.models import Consequence, User, Task
from app.models.consequence import ConsequenceSeverity, RestrictionType
from app.schemas.consequence import ConsequenceCreate, ConsequenceUpdate
from app.core.exceptions import (
    NotFoundException,
    ValidationException,
)


class ConsequenceService:
    """Service for consequence-related operations"""

    @staticmethod
    async def create_consequence(
        db: AsyncSession,
        consequence_data: ConsequenceCreate,
        family_id: UUID,
    ) -> Consequence:
        """Create a new consequence"""
        # Verify user exists and belongs to family
        user = (await db.execute(
            select(User).where(and_(User.id == consequence_data.applied_to_user, User.family_id == family_id))
        )).scalar_one_or_none()
        if not user:
            raise NotFoundException("User not found or does not belong to this family")
        
        # Create consequence
        consequence = Consequence(
            title=consequence_data.title,
            description=consequence_data.description,
            severity=consequence_data.severity,
            restriction_type=consequence_data.restriction_type,
            duration_days=consequence_data.duration_days,
            triggered_by_task_id=consequence_data.triggered_by_task_id,
            applied_to_user=consequence_data.applied_to_user,
            family_id=family_id,
        )
        consequence.apply_consequence()
        
        db.add(consequence)
        await db.commit()
        await db.refresh(consequence)
        return consequence

    @staticmethod
    async def get_consequence(
        db: AsyncSession, consequence_id: UUID, family_id: UUID
    ) -> Consequence:
        """Get a consequence by ID"""
        query = select(Consequence).where(
            and_(Consequence.id == consequence_id, Consequence.family_id == family_id)
        )
        consequence = (await db.execute(query)).scalar_one_or_none()
        if not consequence:
            raise NotFoundException("Consequence not found")
        return consequence

    @staticmethod
    async def list_consequences(
        db: AsyncSession,
        family_id: UUID,
        user_id: Optional[UUID] = None,
        active_only: bool = False,
    ) -> List[Consequence]:
        """List consequences with optional filters"""
        query = select(Consequence).where(Consequence.family_id == family_id)
        
        if user_id:
            query = query.where(Consequence.applied_to_user == user_id)
        if active_only:
            query = query.where(Consequence.active == True)
        
        query = query.order_by(Consequence.created_at.desc())
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def get_active_consequences(
        db: AsyncSession, user_id: UUID
    ) -> List[Consequence]:
        """Get all active consequences for a user"""
        query = select(Consequence).where(
            and_(
                Consequence.applied_to_user == user_id,
                Consequence.active == True,
                Consequence.resolved == False,
            )
        )
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def update_consequence(
        db: AsyncSession,
        consequence_id: UUID,
        consequence_data: ConsequenceUpdate,
        family_id: UUID,
    ) -> Consequence:
        """Update consequence details"""
        consequence = await ConsequenceService.get_consequence(db, consequence_id, family_id)
        
        # Don't allow updates to resolved consequences
        if consequence.resolved:
            raise ValidationException("Cannot update a resolved consequence")
        
        # Update fields if provided
        update_fields = consequence_data.model_dump(exclude_unset=True)
        for field, value in update_fields.items():
            setattr(consequence, field, value)
        
        consequence.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(consequence)
        return consequence

    @staticmethod
    async def resolve_consequence(
        db: AsyncSession,
        consequence_id: UUID,
        family_id: UUID,
    ) -> Consequence:
        """Mark consequence as resolved"""
        consequence = await ConsequenceService.get_consequence(db, consequence_id, family_id)
        
        if consequence.resolved:
            raise ValidationException("Consequence is already resolved")
        
        consequence.resolve_consequence()
        await db.commit()
        await db.refresh(consequence)
        return consequence

    @staticmethod
    async def check_expired_consequences(db: AsyncSession, family_id: UUID) -> List[Consequence]:
        """Check for expired consequences and auto-resolve them"""
        now = datetime.utcnow()
        
        query = select(Consequence).where(
            and_(
                Consequence.family_id == family_id,
                Consequence.active == True,
                Consequence.resolved == False,
                Consequence.end_date < now,
            )
        )
        
        consequences = (await db.execute(query)).scalars().all()
        
        for consequence in consequences:
            consequence.resolve_consequence()
        
        if consequences:
            await db.commit()
        
        return list(consequences)

    @staticmethod
    async def has_active_restriction(
        db: AsyncSession,
        user_id: UUID,
        restriction_type: RestrictionType,
    ) -> bool:
        """Check if user has an active restriction of a specific type"""
        query = select(Consequence).where(
            and_(
                Consequence.applied_to_user == user_id,
                Consequence.active == True,
                Consequence.resolved == False,
                Consequence.restriction_type == restriction_type,
            )
        )
        result = (await db.execute(query)).scalar_one_or_none()
        return result is not None

    @staticmethod
    async def delete_consequence(
        db: AsyncSession, consequence_id: UUID, family_id: UUID
    ) -> None:
        """Delete a consequence"""
        consequence = await ConsequenceService.get_consequence(db, consequence_id, family_id)
        await db.delete(consequence)
        await db.commit()
