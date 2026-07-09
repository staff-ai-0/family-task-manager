"""Virtual pet service (W4.3).

Owner-scoped — a pet belongs to exactly one user. Stat changes are batched
on read via apply_decay so we don't need a real-time tick: every time the
owner opens the pet, we age it forward in 24h slices.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ForbiddenException,
    NotFoundException,
    ValidationException,
)
from app.models.kid_pet import (
    EVOLUTION_STAGE_LABELS,
    EVOLUTION_STAGE_NAMES,
    KidPet,
    VALID_SPECIES,
    stage_for_xp,
)


# Per-day decay deltas (applied once per 24h slice).
HUNGER_RISE_PER_DAY = 20
MOOD_DROP_PER_DAY = 15

# Per-task rewards (W4.3 hooks). Pet XP is awarded when an assignment is
# APPROVED (mandatory silent-complete, gig auto-approve, or parent approve) —
# see on_task_completed, which every approval path already calls.
XP_PER_MANDATORY = 5
XP_PER_GIG = 20
HUNGER_RELIEF_PER_TASK = 8  # tasks slightly feed the pet too
MOOD_BUMP_PER_TASK = 2      # chore streak visibly lifts pet mood


# W5.4: Treat catalog. Kid burns own POINTS to top up pet stats.
# Keys mirror the API's treat_type field.
TREATS: dict[str, dict] = {
    "snack":   {"cost": 5,  "hunger": -10, "mood": 2,  "xp": 0,  "label": "Snack"},
    "toy":     {"cost": 10, "hunger": 0,   "mood": 20, "xp": 0,  "label": "Toy"},
    "vitamin": {"cost": 20, "hunger": -5,  "mood": 5,  "xp": 30, "label": "Vitamin"},
    "gourmet": {"cost": 30, "hunger": -50, "mood": 10, "xp": 15, "label": "Gourmet meal"},
}


# Care economy: feed / wash / play. Each costs POINTS (privileges currency —
# never cash) and restores mood/hunger. Points are the sink that keeps the
# loop meaningful. feed()/play() delegate here so there is ONE paid path.
# feed's magnitudes match the historical free feed/play so existing callers
# see the same stat changes (now point-priced). ``requires_hunger`` rejects a
# wasted feed before charging.
CARE_ACTIONS: dict[str, dict] = {
    "feed": {"cost": 2, "hunger": -30, "mood": 5,  "requires_hunger": True,
             "label": {"es": "Alimentar", "en": "Feed"}},
    "wash": {"cost": 2, "hunger": 0,   "mood": 12, "requires_hunger": False,
             "label": {"es": "Bañar", "en": "Wash"}},
    "play": {"cost": 1, "hunger": 5,   "mood": 15, "requires_hunger": False,
             "label": {"es": "Jugar", "en": "Play"}},
}


# Back-compat aliases (historical free-action magnitudes now live in CARE_ACTIONS).
FEED_HUNGER_DROP = -CARE_ACTIONS["feed"]["hunger"]
FEED_MOOD_BUMP = CARE_ACTIONS["feed"]["mood"]
PLAY_MOOD_BUMP = CARE_ACTIONS["play"]["mood"]
PLAY_HUNGER_RISE = CARE_ACTIONS["play"]["hunger"]


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
        PetService._sync_progression(pet)  # keep the stage cache honest
        await db.commit()
        await db.refresh(pet)
        return pet

    @staticmethod
    async def _spend_points(
        db: AsyncSession, user_id: UUID, cost: int, description: str
    ) -> None:
        """Burn ``cost`` POINTS from the user + log a REWARD_REDEEMED
        transaction (the two-currency privileges sink — never touches cash).
        Raises ValidationException if the balance is short. Does NOT commit —
        folds into the caller's transaction.
        """
        from app.models.point_transaction import PointTransaction, TransactionType

        from app.models.user import User

        if cost <= 0:
            return
        # Lock the user row so two concurrent spends can't both pass the balance
        # check and double-spend / drive points negative.
        user = (
            await db.execute(
                select(User).where(User.id == user_id).with_for_update()
            )
        ).scalar_one_or_none()
        if user is None:
            raise NotFoundException("User not found")
        if user.points < cost:
            raise ValidationException(f"Need {cost} pts, have {user.points}")
        before = user.points
        user.points -= cost
        db.add(
            PointTransaction(
                type=TransactionType.REWARD_REDEEMED,
                user_id=user_id,
                points=-cost,
                balance_before=before,
                balance_after=user.points,
                description=description,
            )
        )

    @staticmethod
    async def care(db: AsyncSession, user_id: UUID, action: str) -> KidPet:
        """Paid care action (feed/wash/play) on the user's OWN pet.

        Costs POINTS (rejects if short — no partial spend) and restores
        mood/hunger. ``feed`` rejects a not-hungry pet BEFORE charging so a
        wasted tap costs nothing.
        """
        if action not in CARE_ACTIONS:
            raise ValidationException(f"Unknown care action: {action}")
        spec = CARE_ACTIONS[action]
        pet = await PetService.get_or_404(db, user_id)
        if spec["requires_hunger"] and pet.hunger <= 0:
            raise ValidationException("Pet is not hungry")
        await PetService._spend_points(
            db, user_id, spec["cost"], f"Pet care: {action}"
        )
        pet.hunger = _clamp(pet.hunger + spec["hunger"])
        pet.mood = _clamp(pet.mood + spec["mood"])
        await db.commit()
        await db.refresh(pet)
        return pet

    @staticmethod
    async def feed(db: AsyncSession, user_id: UUID) -> KidPet:
        """Legacy name — now the paid care action ``feed``."""
        return await PetService.care(db, user_id, "feed")

    @staticmethod
    async def play(db: AsyncSession, user_id: UUID) -> KidPet:
        """Legacy name — now the paid care action ``play``."""
        return await PetService.care(db, user_id, "play")

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
            await db.execute(
                sa_select(User).where(User.id == user_id).with_for_update()
            )
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
        # Keep the cached evolution_stage in sync — a treat can cross a threshold.
        PetService._sync_progression(pet)

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

        # Skip pets in soft-deleted (closed) families — soft delete stamps
        # deleted_at on every member user, so filter on the owner.
        rows = (await db.execute(
            sa_select(KidPet)
            .join(User, User.id == KidPet.user_id)
            .where(User.deleted_at.is_(None))
        )).scalars().all()
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
                from app.services.notification_service import (
                    NotificationService,
                )
                title, body = NotificationService.render(
                    "pet_starving" if after_label == "starving" else "pet_sad",
                    getattr(user, "preferred_lang", None) or "es",
                    {"pet": pet.name},
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
    def _sync_progression(pet: KidPet) -> None:
        """Recompute the cached evolution_stage from xp so it never drifts."""
        pet.evolution_stage = stage_for_xp(pet.xp or 0)

    @staticmethod
    async def on_task_completed(
        db: AsyncSession, user_id: UUID, *, is_bonus: bool
    ) -> None:
        """Hook invoked when the owner's assignment is APPROVED — every
        approval path (mandatory silent-complete, gig auto-approve, parent
        approve) already calls this, so pet XP rides the existing hook rather
        than a parallel one.

        Awards pet XP, nudges mood (chore streak → happier pet) + hunger,
        advances the evolution stage, and fires ONE bilingual level-up /
        evolution notification on a threshold crossing.

        Safe-no-op if the user has no pet (most parents won't). Best-effort:
        a pet/notification failure never breaks the surrounding approval. Does
        not commit; the caller's outer transaction wraps the points award.
        """
        # Best-effort: a pet failure must NEVER roll back the surrounding
        # points award / approval, which commit in the caller's transaction
        # AFTER this hook returns. The whole body is guarded — the realistic
        # throw vectors here are in-memory (no DB write before commit), so a
        # caught failure leaves the session clean for the outer commit.
        try:
            await PetService._apply_task_reward(db, user_id, is_bonus=is_bonus)
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                "pet on_task_completed failed (best-effort; approval unaffected)"
            )

    @staticmethod
    async def _apply_task_reward(
        db: AsyncSession, user_id: UUID, *, is_bonus: bool
    ) -> None:
        pet = await PetService.get_for_user(db, user_id)
        if not pet:
            return
        PetService.apply_decay_in_place(pet)

        before_level = pet.level
        before_stage = stage_for_xp(pet.xp)

        delta_xp = XP_PER_GIG if is_bonus else XP_PER_MANDATORY
        pet.xp = max(0, pet.xp + delta_xp)
        pet.hunger = _clamp(pet.hunger - HUNGER_RELIEF_PER_TASK)
        pet.mood = _clamp(pet.mood + MOOD_BUMP_PER_TASK)
        PetService._sync_progression(pet)

        after_level = pet.level
        after_stage = pet.evolution_stage

        if after_stage > before_stage or after_level > before_level:
            await PetService._notify_progression(
                db,
                pet,
                user_id,
                leveled_up=after_level > before_level,
                evolved=after_stage > before_stage,
                level=after_level,
                stage=after_stage,
            )

    @staticmethod
    async def _notify_progression(
        db: AsyncSession,
        pet: KidPet,
        user_id: UUID,
        *,
        leveled_up: bool,
        evolved: bool,
        level: int,
        stage: int,
    ) -> None:
        """Emit ONE bilingual progression notification (evolution takes
        precedence over a same-tick level-up — it's the bigger moment). Uses
        create_localized_no_commit so it folds into the caller's approval txn;
        no push here (the caller owns the commit)."""
        from app.models.user import User
        from app.services.notification_service import NotificationService

        user = await db.get(User, user_id)
        if user is None or user.family_id is None:
            return
        if evolved:
            key = "pet_evolved"
            params = {
                "pet": pet.name,
                "stage": EVOLUTION_STAGE_LABELS.get(stage, {"es": "", "en": ""}),
            }
        else:
            key = "pet_level_up"
            params = {"pet": pet.name, "level": level}
        await NotificationService.create_localized_no_commit(
            db,
            family_id=user.family_id,
            key=key,
            user_id=user_id,
            params=params,
            link="/pet",
        )

    # ─── Authorization (per-kid + family isolation) ──────────────────

    @staticmethod
    async def resolve_target(
        db: AsyncSession,
        actor,
        target_user_id: Optional[UUID],
        *,
        action: bool,
    ) -> UUID:
        """Resolve + authorize the pet-owner a request targets.

        - Target defaults to the actor.
        - ACTIONS (care / buy / equip) are self-only: any target != actor is
          403 — a kid acts only on their own pet; parents may VIEW but not act.
        - VIEW: self always; a PARENT may view any same-family member; anyone
          else viewing a sibling is 403. Cross-family is always 403.
        """
        from app.models.user import UserRole
        from app.services.base_service import get_user_by_id

        if target_user_id is None or target_user_id == actor.id:
            return actor.id
        if action:
            raise ForbiddenException("You can only act on your own pet")
        target = await get_user_by_id(db, target_user_id)
        if target.family_id != actor.family_id:
            raise ForbiddenException("Pet is not in your family")
        if actor.role != UserRole.PARENT:
            raise ForbiddenException("You can only view your own pet")
        return target_user_id

    # ─── Cosmetics (points sink · stage-gated) ───────────────────────

    @staticmethod
    async def _owned_cosmetics(db: AsyncSession, pet_id: UUID) -> list:
        from app.models.pet_cosmetic import PetCosmetic

        rows = (
            await db.execute(
                select(PetCosmetic).where(PetCosmetic.pet_id == pet_id)
            )
        ).scalars().all()
        return list(rows)

    @staticmethod
    async def list_cosmetics(db: AsyncSession, user_id: UUID) -> dict:
        """Static catalog annotated per the user's own pet: owned / equipped /
        unlocked (stage gate) / affordable (points). Read-only."""
        from app.services.base_service import get_user_by_id
        from app.services.pet_cosmetics import catalog_public

        pet = await PetService.get_or_404(db, user_id)
        user = await get_user_by_id(db, user_id)
        owned = {
            c.cosmetic_key: c
            for c in await PetService._owned_cosmetics(db, pet.id)
        }
        items = []
        for entry in catalog_public():
            rec = owned.get(entry["key"])
            items.append(
                {
                    **entry,
                    "owned": rec is not None,
                    "equipped": bool(rec.equipped) if rec else False,
                    "unlocked": pet.evolution_stage >= entry["min_stage"],
                    "affordable": user.points >= entry["price"],
                }
            )
        return {
            "points": user.points,
            "evolution_stage": pet.evolution_stage,
            "evolution_stage_name": pet.evolution_stage_name,
            "cosmetics": items,
        }

    @staticmethod
    async def buy_cosmetic(db: AsyncSession, user_id: UUID, cosmetic_key: str):
        """Buy a cosmetic for the user's OWN pet with POINTS. Requires the
        pet to have reached the cosmetic's ``min_stage`` and enough points;
        rejects a duplicate purchase."""
        from app.models.pet_cosmetic import PetCosmetic
        from app.services.pet_cosmetics import cosmetic_or_none

        spec = cosmetic_or_none(cosmetic_key)
        if spec is None:
            raise ValidationException(f"Unknown cosmetic: {cosmetic_key}")
        pet = await PetService.get_or_404(db, user_id)
        if pet.evolution_stage < spec["min_stage"]:
            raise ValidationException(
                f"Locked — unlocks at evolution stage {spec['min_stage']} "
                f"({EVOLUTION_STAGE_NAMES[spec['min_stage']]})"
            )
        existing = (
            await db.execute(
                select(PetCosmetic).where(
                    PetCosmetic.pet_id == pet.id,
                    PetCosmetic.cosmetic_key == cosmetic_key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise ValidationException("You already own this cosmetic")
        await PetService._spend_points(
            db, user_id, spec["price"], f"Pet cosmetic: {spec['name']['en']}"
        )
        rec = PetCosmetic(
            pet_id=pet.id, cosmetic_key=cosmetic_key, equipped=False
        )
        db.add(rec)
        try:
            await db.commit()
        except IntegrityError:
            # Concurrent duplicate buy — the unique constraint rolled this txn
            # back (including its point spend), so surface a clean error.
            await db.rollback()
            raise ValidationException("You already own this cosmetic")
        await db.refresh(rec)
        return rec

    @staticmethod
    async def equip_cosmetic(
        db: AsyncSession, user_id: UUID, cosmetic_key: str, equip: bool = True
    ):
        """Equip (or unequip) an OWNED cosmetic on the user's own pet. Free.
        Equipping unequips any other owned cosmetic in the same slot."""
        from app.models.pet_cosmetic import PetCosmetic
        from app.services.pet_cosmetics import COSMETICS, cosmetic_or_none

        spec = cosmetic_or_none(cosmetic_key)
        if spec is None:
            raise ValidationException(f"Unknown cosmetic: {cosmetic_key}")
        pet = await PetService.get_or_404(db, user_id)
        rec = (
            await db.execute(
                select(PetCosmetic).where(
                    PetCosmetic.pet_id == pet.id,
                    PetCosmetic.cosmetic_key == cosmetic_key,
                )
            )
        ).scalar_one_or_none()
        if rec is None:
            raise ValidationException("You don't own this cosmetic")
        if equip:
            slot_keys = [
                k for k, c in COSMETICS.items() if c["slot"] == spec["slot"]
            ]
            others = (
                await db.execute(
                    select(PetCosmetic).where(
                        PetCosmetic.pet_id == pet.id,
                        PetCosmetic.cosmetic_key.in_(slot_keys),
                        PetCosmetic.equipped.is_(True),
                    )
                )
            ).scalars().all()
            for o in others:
                o.equipped = False
            rec.equipped = True
        else:
            rec.equipped = False
        await db.commit()
        await db.refresh(rec)
        return rec

    @staticmethod
    async def equipped_cosmetics(db: AsyncSession, pet_id: UUID) -> list[dict]:
        """The pet's currently-equipped cosmetics, resolved to catalog data."""
        from app.models.pet_cosmetic import PetCosmetic
        from app.services.pet_cosmetics import cosmetic_or_none

        rows = (
            await db.execute(
                select(PetCosmetic).where(
                    PetCosmetic.pet_id == pet_id,
                    PetCosmetic.equipped.is_(True),
                )
            )
        ).scalars().all()
        out = []
        for r in rows:
            spec = cosmetic_or_none(r.cosmetic_key) or {}
            out.append(
                {
                    "key": r.cosmetic_key,
                    "slot": spec.get("slot"),
                    "icon": spec.get("icon"),
                    "name": spec.get("name"),
                }
            )
        return out

    # ─── Quest view (read-only kid UI payload) ───────────────────────

    @staticmethod
    def pet_state_dict(pet: KidPet, equipped: list[dict]) -> dict:
        """Serialize the evolved pet state for quest-mode clients."""
        return {
            "id": pet.id,
            "name": pet.name,
            "species": pet.species,
            "mood": pet.mood,
            "hunger": pet.hunger,
            "xp": pet.xp,
            "level": pet.level,
            "xp_to_next_level": pet.xp_to_next_level,
            "evolution_stage": pet.evolution_stage,
            "evolution_stage_name": pet.evolution_stage_name,
            "xp_to_next_stage": pet.xp_to_next_stage,
            "status_label": pet.status_label,
            "equipped_cosmetics": equipped,
        }

    @staticmethod
    async def quest_view(
        db: AsyncSession, user_id: UUID, family_id: UUID
    ) -> dict:
        """Today's assignments rendered as quests + current pet state — the
        payload a quest-mode kid UI needs. Read-only."""
        from app.services.task_assignment_service import TaskAssignmentService

        rows = await TaskAssignmentService.list_for_user_today_with_locks(
            db, user_id, family_id
        )
        quests = []
        for r in rows:
            is_bonus = bool(r.get("is_bonus"))
            status = r.get("status")
            quests.append(
                {
                    "assignment_id": r.get("id"),
                    "template_id": r.get("template_id"),
                    "title": r.get("title"),
                    "title_es": r.get("title_es"),
                    "points": r.get("points"),
                    "pet_xp_reward": XP_PER_GIG if is_bonus else XP_PER_MANDATORY,
                    "is_bonus": is_bonus,
                    "status": status,
                    "approval_status": r.get("approval_status"),
                    "is_locked": bool(r.get("is_locked")),
                    "done": status == "completed",
                }
            )

        pet_state = None
        pet = await PetService.get_for_user(db, user_id)
        if pet:
            PetService.apply_decay_in_place(pet)
            PetService._sync_progression(pet)
            await db.commit()
            await db.refresh(pet)
            equipped = await PetService.equipped_cosmetics(db, pet.id)
            pet_state = PetService.pet_state_dict(pet, equipped)

        today = await TaskAssignmentService._user_local_today(db, user_id)
        return {"date": today, "pet": pet_state, "quests": quests}
