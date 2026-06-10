"""OnboardingService — track first-run checklist completion per family."""
import logging
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.family import Family
from app.schemas.onboarding import OnboardingState

log = logging.getLogger(__name__)

VALID_STEPS = frozenset([
    "child_invited", "task_created", "reward_created", "points_awarded",
])


class OnboardingService:

    @staticmethod
    async def advance(family_id: UUID, step: str, db: AsyncSession) -> None:
        """Set onboarding_{step}=True idempotently. Caller must commit."""
        if step not in VALID_STEPS:
            log.warning("OnboardingService.advance: unknown step %r", step)
            return
        col = f"onboarding_{step}"
        await db.execute(
            update(Family)
            .where(Family.id == family_id, getattr(Family, col).is_(False))
            .values({col: True})
        )

    @staticmethod
    async def get_state(family_id: UUID, db: AsyncSession) -> OnboardingState:
        row = await db.get(Family, family_id)
        if not row:
            return OnboardingState(
                child_invited=False, task_created=False,
                reward_created=False, points_awarded=False,
                dismissed=False,
            )
        return OnboardingState(
            child_invited=row.onboarding_child_invited,
            task_created=row.onboarding_task_created,
            reward_created=row.onboarding_reward_created,
            points_awarded=row.onboarding_points_awarded,
            dismissed=row.onboarding_dismissed,
        )

    @staticmethod
    async def dismiss(family_id: UUID, db: AsyncSession) -> None:
        await db.execute(
            update(Family)
            .where(Family.id == family_id)
            .values(onboarding_dismissed=True)
        )
        await db.commit()
