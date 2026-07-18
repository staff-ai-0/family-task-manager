"""OnboardingService — track first-run checklist completion per family."""
import logging
from uuid import UUID

from sqlalchemy import update, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.family import Family
from app.models.user import User
from app.models.onboarding_event import OnboardingEvent, ONBOARDING_EVENT_TYPES
from app.schemas.onboarding import (
    OnboardingState,
    OnboardingAnalytics,
    MemberOnboarding,
)

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
        # Derived optional step: has this family ever imported a scanned
        # flyer? (calendar_events.source='ocr_flyer' — set by the /calendar
        # scan flow). Derived on read so no new family column is needed.
        from app.models.calendar_event import CalendarEvent
        flyer_scanned = (await db.execute(
            select(CalendarEvent.id).where(
                CalendarEvent.family_id == family_id,
                CalendarEvent.source == "ocr_flyer",
            ).limit(1)
        )).scalar_one_or_none() is not None
        # Derived optional step: has this family ever posted a gig? Mirrors the
        # flyer_scanned pattern so no new family column is needed.
        from app.models.gig import GigOffering
        gig_created = (await db.execute(
            select(GigOffering.id).where(
                GigOffering.family_id == family_id,
            ).limit(1)
        )).scalar_one_or_none() is not None
        return OnboardingState(
            child_invited=row.onboarding_child_invited,
            task_created=row.onboarding_task_created,
            reward_created=row.onboarding_reward_created,
            points_awarded=row.onboarding_points_awarded,
            dismissed=row.onboarding_dismissed,
            flyer_scanned=flyer_scanned,
            gig_created=gig_created,
        )

    @staticmethod
    async def dismiss(family_id: UUID, db: AsyncSession) -> None:
        await db.execute(
            update(Family)
            .where(Family.id == family_id)
            .values(onboarding_dismissed=True)
        )
        await db.commit()

    @staticmethod
    async def record_event(
        user: User, event_type: str, step_index, db: AsyncSession
    ) -> bool:
        """Record a welcome-tour funnel event. Returns False for unknown types."""
        if event_type not in ONBOARDING_EVENT_TYPES:
            log.warning("OnboardingService.record_event: unknown type %r", event_type)
            return False
        db.add(OnboardingEvent(
            user_id=user.id,
            family_id=user.family_id,
            event_type=event_type,
            step_index=step_index,
        ))
        await db.commit()
        return True

    @staticmethod
    async def get_analytics(family_id: UUID, db: AsyncSession) -> OnboardingAnalytics:
        """Funnel summary: per-member tour status + family checklist progress."""
        members = (await db.execute(
            select(User).where(
                User.family_id == family_id, User.is_active.is_(True)
            )
        )).scalars().all()
        event_rows = (await db.execute(
            select(OnboardingEvent.user_id, OnboardingEvent.event_type)
            .where(OnboardingEvent.family_id == family_id)
        )).all()

        by_user: dict = {}
        for uid, etype in event_rows:
            by_user.setdefault(uid, set()).add(etype)

        def status_for(u: User) -> str:
            types = by_user.get(u.id, set())
            if "tour_completed" in types:
                return "completed"
            if "tour_skipped" in types:
                return "skipped"
            if "tour_started" in types:
                return "started"
            return "not_started"

        rows = []
        counts = {"completed": 0, "skipped": 0, "started": 0, "not_started": 0}
        for u in members:
            st = status_for(u)
            counts[st] += 1
            rows.append(MemberOnboarding(
                user_id=str(u.id),
                name=u.name,
                role=u.role.value if hasattr(u.role, "value") else str(u.role),
                completed_welcome_tour=bool(u.completed_welcome_tour),
                tour_status=st,
            ))

        checklist = await OnboardingService.get_state(family_id, db)
        return OnboardingAnalytics(
            total_members=len(members),
            tour_completed=counts["completed"],
            tour_skipped=counts["skipped"],
            tour_started=counts["started"],
            tour_not_started=counts["not_started"],
            checklist=checklist,
            members=rows,
        )
