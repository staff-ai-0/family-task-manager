"""Virtual pet service (W4.3).

Owner-scoped — a pet belongs to exactly one user. Stat changes are batched
on read via apply_decay so we don't need a real-time tick: every time the
owner opens the pet, we age it forward in 24h slices.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException, ValidationException
from app.models.kid_pet import KidPet, VALID_SPECIES


# Per-day decay deltas (applied once per 24h slice).
HUNGER_RISE_PER_DAY = 20
MOOD_DROP_PER_DAY = 15

# Per-task rewards (W4.3 hooks).
XP_PER_MANDATORY = 5
XP_PER_GIG = 20
HUNGER_RELIEF_PER_TASK = 8  # tasks slightly feed the pet too

# Per-action effects.
FEED_HUNGER_DROP = 30
FEED_MOOD_BUMP = 5
PLAY_MOOD_BUMP = 15
PLAY_HUNGER_RISE = 5


# W5.4: Treat catalog. Kid burns own points to top up pet stats.
# Keys mirror the API's treat_type field.
TREATS: dict[str, dict] = {
    "snack":   {"cost": 5,  "hunger": -10, "mood": 2,  "xp": 0,  "label": "Snack"},
    "toy":     {"cost": 10, "hunger": 0,   "mood": 20, "xp": 0,  "label": "Toy"},
    "vitamin": {"cost": 20, "hunger": -5,  "mood": 5,  "xp": 30, "label": "Vitamin"},
    "gourmet": {"cost": 30, "hunger": -50, "mood": 10, "xp": 15, "label": "Gourmet meal"},
}


def _clamp(value: int, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, value))


class PetService:
    @staticmethod
    async def get_for_user(
        db: AsyncSession, user_id: UUID
    ) -> Optional[KidPet]:
        q = select(KidPet).where(KidPet.user_id == user_id)
        return (await db.execute(q)).scalar_one_or_none()

    @staticmethod
    async def create_for_user(
        db: AsyncSession,
        user_id: UUID,
        name: str,
        species: str = "cat",
    ) -> KidPet:
        existing = await PetService.get_for_user(db, user_id)
        if existing:
            raise ValidationException("This user already has a pet")
        if species not in VALID_SPECIES:
            raise ValidationException(f"Invalid species: {species}")
        if not name or not name.strip():
            raise ValidationException("Pet name required")
        pet = KidPet(user_id=user_id, name=name.strip()[:40], species=species)
        db.add(pet)
        await db.commit()
        await db.refresh(pet)
        return pet

    @staticmethod
    def apply_decay_in_place(pet: KidPet, now: Optional[datetime] = None) -> KidPet:
        """Age the pet forward in 24h slices since last_decay_at.

        Caller is responsible for the surrounding transaction.
        """
        now = now or datetime.now(timezone.utc)
        elapsed = now - pet.last_decay_at
        days = int(elapsed.total_seconds() // 86400)
        if days <= 0:
            return pet
        pet.hunger = _clamp(pet.hunger + HUNGER_RISE_PER_DAY * days)
        pet.mood = _clamp(pet.mood - MOOD_DROP_PER_DAY * days)
        pet.last_decay_at = pet.last_decay_at + timedelta(days=days)
        return pet

    @staticmethod
    async def get_or_404(db: AsyncSession, user_id: UUID) -> KidPet:
        pet = await PetService.get_for_user(db, user_id)
        if not pet:
            raise NotFoundException("No pet — create one first")
        PetService.apply_decay_in_place(pet)
        await db.commit()
        await db.refresh(pet)
        return pet

    @staticmethod
    async def feed(db: AsyncSession, user_id: UUID) -> KidPet:
        pet = await PetService.get_or_404(db, user_id)
        if pet.hunger <= 0:
            raise ValidationException("Pet is not hungry")
        pet.hunger = _clamp(pet.hunger - FEED_HUNGER_DROP)
        pet.mood = _clamp(pet.mood + FEED_MOOD_BUMP)
        await db.commit()
        await db.refresh(pet)
        return pet

    @staticmethod
    async def play(db: AsyncSession, user_id: UUID) -> KidPet:
        pet = await PetService.get_or_404(db, user_id)
        pet.mood = _clamp(pet.mood + PLAY_MOOD_BUMP)
        pet.hunger = _clamp(pet.hunger + PLAY_HUNGER_RISE)
        await db.commit()
        await db.refresh(pet)
        return pet

    @staticmethod
    async def give_treat(
        db: AsyncSession, user_id: UUID, treat_type: str
    ) -> KidPet:
        from app.models.point_transaction import PointTransaction, TransactionType
        from app.models.user import User
        from sqlalchemy import select as sa_select

        if treat_type not in TREATS:
            raise ValidationException(f"Unknown treat: {treat_type}")
        treat = TREATS[treat_type]

        user = (
            await db.execute(sa_select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if user is None:
            raise NotFoundException("User not found")
        if user.points < treat["cost"]:
            raise ValidationException(
                f"Need {treat['cost']} pts, have {user.points}"
            )

        pet = await PetService.get_or_404(db, user_id)

        # Burn points + log transaction
        before = user.points
        user.points -= treat["cost"]
        db.add(PointTransaction(
            type=TransactionType.REWARD_REDEEMED,
            user_id=user_id,
            points=-treat["cost"],
            balance_before=before,
            balance_after=user.points,
            description=f"Pet treat: {treat['label']}",
        ))

        # Apply effects
        pet.hunger = _clamp(pet.hunger + treat["hunger"])
        pet.mood = _clamp(pet.mood + treat["mood"])
        pet.xp = max(0, pet.xp + treat["xp"])

        await db.commit()
        await db.refresh(pet)
        return pet

    @staticmethod
    async def sweep_decay_all(db: AsyncSession) -> int:
        """Apply pending decay slices to every pet + notify owners of new
        sad/starving states. Intended for a daily cron tick.

        Returns the number of pets whose state changed enough to fire a
        notification (i.e. crossed into starving/sad since the last sweep).
        """
        from app.models.notification import Notification, NotificationType
        from app.models.user import User
        from sqlalchemy import select as sa_select

        rows = (await db.execute(sa_select(KidPet))).scalars().all()
        notified = 0
        for pet in rows:
            before_label = pet.status_label
            PetService.apply_decay_in_place(pet)
            after_label = pet.status_label
            if after_label in ("starving", "sad") and before_label not in (
                "starving",
                "sad",
            ):
                user = (
                    await db.execute(
                        sa_select(User).where(User.id == pet.user_id)
                    )
                ).scalar_one_or_none()
                if user is None or user.family_id is None:
                    continue
                title = (
                    f"🥺 {pet.name} is starving"
                    if after_label == "starving"
                    else f"😞 {pet.name} is sad"
                )
                body = (
                    "Feed them before they get too hungry."
                    if after_label == "starving"
                    else "Play or feed them to cheer them up."
                )
                db.add(
                    Notification(
                        family_id=user.family_id,
                        user_id=pet.user_id,
                        type=NotificationType.PET_NEEDS_ATTENTION,
                        title=title,
                        body=body,
                        link="/pet",
                    )
                )
                # Best-effort push so the device buzzes too.
                try:
                    from app.services.push_service import PushService
                    await PushService.send_to_user(
                        db,
                        pet.user_id,
                        {"title": title, "body": body, "url": "/pet"},
                    )
                except Exception:
                    import logging
                    logging.getLogger(__name__).exception(
                        "pet attention push failed"
                    )
                notified += 1
        await db.commit()
        return notified

    @staticmethod
    async def on_task_completed(
        db: AsyncSession, user_id: UUID, *, is_bonus: bool
    ) -> None:
        """Hook invoked when the owner finishes a task or gig.

        Safe-no-op if the user has no pet (most parents won't). Does not
        commit; caller's outer transaction wraps the points award.
        """
        pet = await PetService.get_for_user(db, user_id)
        if not pet:
            return
        PetService.apply_decay_in_place(pet)
        delta_xp = XP_PER_GIG if is_bonus else XP_PER_MANDATORY
        pet.xp = max(0, pet.xp + delta_xp)
        pet.hunger = _clamp(pet.hunger - HUNGER_RELIEF_PER_TASK)
        pet.mood = _clamp(pet.mood + 2)
