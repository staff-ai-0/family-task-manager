"""
Family Service

Business logic for family group management.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from typing import List, Optional
from datetime import datetime, timezone
from uuid import UUID

from app.models import Family, User, Reward, Consequence
from app.models.task_assignment import TaskAssignment, AssignmentStatus
from app.models.family import generate_join_code
from app.schemas.family import FamilyCreate, FamilyUpdate
from app.core.exceptions import NotFoundException, ValidationException


class FamilyService:
    """Service for family-related operations"""

    # Default gig starter pack.
    # NOTE: this list is duplicated in
    # `backend/migrations/versions/2026_05_22_mandatory_zero_points_and_gigs.py`
    # because migrations must be self-contained (they cannot safely import
    # application code that changes over time). Keep the two copies in sync
    # if the canonical content ever changes.
    DEFAULT_GIGS = [
        ("Learn a topic + writeup", "Pick something new (podman, git, a recipe). Read up, then write 5-10 sentences on what you learned.", 30),
        ("Read book chapter + discuss", "Read a chapter, then sit with a parent to discuss the main idea.", 20),
        ("Plan next 3 days of meals", "Propose breakfasts, lunches, and dinners for the next 3 days. List groceries needed.", 25),
        ("Help with grocery shopping", "Help compile the list, go to the store, and help carry/put away.", 15),
        ("Cook family dinner", "Plan, cook, and serve a family dinner with parent supervision.", 25),
        ("Tech-help parent (15 min)", "Help a parent with a phone/computer task for at least 15 minutes.", 10),
    ]

    @staticmethod
    async def _seed_default_gigs(db: AsyncSession, family_id: UUID) -> None:
        from app.models.task_template import TaskTemplate, AssignmentType

        titles = [t for t, _, _ in FamilyService.DEFAULT_GIGS]
        existing = (await db.execute(
            select(TaskTemplate.title).where(
                TaskTemplate.family_id == family_id,
                TaskTemplate.title.in_(titles),
            )
        )).scalars().all()
        existing_set = set(existing)

        for title, description, points in FamilyService.DEFAULT_GIGS:
            if title in existing_set:
                continue
            db.add(TaskTemplate(
                title=title,
                description=description,
                points=points,
                interval_days=7,
                assignment_type=AssignmentType.AUTO,
                is_bonus=True,
                is_active=True,
                family_id=family_id,
            ))
        await db.flush()

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

        await FamilyService._seed_default_gigs(db, family.id)
        await db.commit()

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
                family.updated_at = datetime.now(timezone.utc)
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
                Family.deleted_at.is_(None),  # never join a closing family
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

        # AI opt-in decisions are timestamped so "never decided" (NULL) is
        # distinguishable from an explicit opt-out — the parent dashboard
        # shows a one-time prompt banner only while NULL.
        if "ai_processing_consent" in update_fields:
            family.ai_processing_consent_at = datetime.now(timezone.utc).replace(
                tzinfo=None
            )

        family.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(family)
        return family

    @staticmethod
    async def has_ai_processing_consent(db: AsyncSession, family_id: UUID) -> bool:
        """True when a parent opted in to AI processing of kid-generated
        content (gig proof photos, family chat reads by Jarvis/MCP).

        Cheap scalar query — used inline by AI gate checks. Missing family or
        unset value counts as no consent.
        """
        value = (
            await db.execute(
                select(Family.ai_processing_consent).where(Family.id == family_id)
            )
        ).scalar_one_or_none()
        return bool(value)

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
        
        # Count task assignments (current task system)
        total_tasks = (await db.execute(
            select(func.count())
            .select_from(TaskAssignment)
            .where(TaskAssignment.family_id == family_id)
        )).scalar()

        completed_tasks = (await db.execute(
            select(func.count())
            .select_from(TaskAssignment)
            .where(
                and_(
                    TaskAssignment.family_id == family_id,
                    TaskAssignment.status == AssignmentStatus.COMPLETED,
                )
            )
        )).scalar()

        pending_tasks = (await db.execute(
            select(func.count())
            .select_from(TaskAssignment)
            .where(
                and_(
                    TaskAssignment.family_id == family_id,
                    TaskAssignment.status == AssignmentStatus.PENDING,
                )
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
