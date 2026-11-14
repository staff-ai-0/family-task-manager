"""
Family Service

Business logic for family group management.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
import logging
from typing import List, Optional
from datetime import datetime, timezone
from uuid import UUID

from app.models import Family, User, Reward, Consequence
from app.models.task_assignment import TaskAssignment, AssignmentStatus
from app.models.family import generate_join_code
from app.schemas.family import FamilyCreate, FamilyUpdate
from app.core.exceptions import NotFoundException, ValidationException

logger = logging.getLogger(__name__)


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
        # Early Bird: every off->on re-stamps enabled_at (the week you switch
        # it on never counts) and every on->off files the closed period in
        # early_bird_past_periods. Decide before the loop overwrites the flag.
        for col in (
            "early_bird_enabled", "early_bird_deadline", "early_bird_bonus_pct",
            "early_bird_week_pct", "early_bird_streak_cents",
            "chore_cutoff", "grab_window_end", "teen_alarm_1", "teen_alarm_2",
        ):  # NOT NULL columns: an explicit null means "leave as-is"
            if update_fields.get(col, 0) is None:
                del update_fields[col]
        # Chore rules v2: order checks run on the MERGED values, so moving the
        # deadline past the stored cutoff is refused too.
        merged = {
            col: update_fields.get(col, getattr(family, col))
            for col in (
                "early_bird_deadline", "chore_cutoff", "grab_window_end",
                "teen_alarm_1", "teen_alarm_2",
            )
        }
        if any(c in update_fields for c in merged):
            if merged["chore_cutoff"] <= merged["early_bird_deadline"]:
                raise ValidationException("chore_cutoff must be after early_bird_deadline")
            if merged["grab_window_end"] <= merged["chore_cutoff"]:
                raise ValidationException("grab_window_end must be after chore_cutoff")
            if merged["teen_alarm_1"] >= merged["teen_alarm_2"]:
                raise ValidationException("teen_alarm_1 must be before teen_alarm_2")
            # Strictly before: an alarm AT the cutoff would announce "due by
            # 20:30" at the instant the chores stop being the teen's.
            if merged["teen_alarm_2"] >= merged["chore_cutoff"]:
                raise ValidationException("teen alarms must be before chore_cutoff")
        rules_changed = False
        # Any real change to a rule-defining setting bumps rules_version in
        # the same transaction (unchanged values do not). These are the values
        # the rules sheet shows and RulesService.snapshot records.
        if any(
            col in update_fields and update_fields[col] != getattr(family, col)
            for col in (
                "chore_cutoff", "grab_window_end", "teen_alarm_1", "teen_alarm_2",
                "early_bird_deadline", "early_bird_streak_cents", "early_bird_bonus_pct",
            )
        ):
            family.rules_version = (family.rules_version or 1) + 1
            rules_changed = True
        turning_on = (
            update_fields.get("early_bird_enabled") is True
            and not family.early_bird_enabled
        )
        turning_off = (
            update_fields.get("early_bird_enabled") is False
            and family.early_bird_enabled
        )
        for field, value in update_fields.items():
            setattr(family, field, value)

        # AI opt-in decisions are timestamped so "never decided" (NULL) is
        # distinguishable from an explicit opt-out — the parent dashboard
        # shows a one-time prompt banner only while NULL.
        if "ai_processing_consent" in update_fields:
            family.ai_processing_consent_at = datetime.now(timezone.utc).replace(
                tzinfo=None
            )

        # The teen check-in stores a minor's answers for the product team, so
        # every answer a parent gives (on, off, or back to undecided) is dated.
        if "teen_checkin_enabled" in update_fields:
            family.teen_checkin_decided_at = datetime.now(timezone.utc)

        if turning_on:
            family.early_bird_enabled_at = datetime.now(timezone.utc)
        if turning_off and family.early_bird_enabled_at is not None:
            # Keep the period this switch-off closes: the next off->on
            # re-stamps enabled_at, and the weeks already run must still count.
            from app.services.early_bird_rules import close_period
            family.early_bird_past_periods = close_period(
                family.early_bird_past_periods,
                family.early_bird_enabled_at,
                datetime.now(timezone.utc),
            )

        family.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(family)
        # Tell the members once the save is safely stored. Best effort: a
        # push/notification failure must never fail or undo the settings save.
        if (rules_changed or turning_on) and family.early_bird_enabled:
            try:
                from app.services.rules_service import RulesService

                await RulesService.announce(db, family_id, force=True)
            except Exception:
                logger.exception("rules auto-announce failed for family %s", family_id)
                await db.rollback()
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
