"""Pet quest + evolution loop (2026-07-09).

Covers XP-on-approval (not on rejection), level/evolution threshold crossings +
notifications, the POINTS-only care economy, stage-gated cosmetics, the
read-only quest view, and per-kid + family isolation. Guards the two-currency
rule: the pet loop spends POINTS and never touches cash.
"""

from datetime import date
from uuid import uuid4

import pytest

from app.core.exceptions import ForbiddenException, ValidationException
from app.models.kid_pet import KidPet, stage_for_xp
from app.models.notification import Notification, NotificationType
from app.models.pet_cosmetic import PetCosmetic
from app.models.point_transaction import PointTransaction
from app.models.task_assignment import (
    ApprovalStatus,
    AssignmentStatus,
    TaskAssignment,
)
from app.models.task_template import AssignmentType, TaskTemplate
from app.models.user import User, UserRole
from app.services.pet_service import (
    CARE_ACTIONS,
    XP_PER_GIG,
    XP_PER_MANDATORY,
    PetService,
)
from app.services.pet_cosmetics import COSMETICS


# ── helpers ──────────────────────────────────────────────────────────


async def _mk_user(db, family, *, role=UserRole.CHILD, points=100, cash=0):
    u = User(
        email=f"{uuid4().hex[:10]}@t.com",
        name="Kid",
        role=role,
        family_id=family.id,
        email_verified=True,
        points=points,
        cash_cents=cash,
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def _mk_pet(db, user, *, xp=0, mood=80, hunger=50):
    pet = await PetService.create_for_user(db, user.id, "Buddy", "cat")
    pet.xp = xp
    pet.mood = mood
    pet.hunger = hunger
    PetService._sync_progression(pet)
    await db.commit()
    await db.refresh(pet)
    return pet


async def _neg_point_txns(db, user_id):
    from sqlalchemy import select

    rows = (
        await db.execute(
            select(PointTransaction).where(
                PointTransaction.user_id == user_id,
                PointTransaction.points < 0,
            )
        )
    ).scalars().all()
    return list(rows)


# ── XP on approval / not on rejection ────────────────────────────────


class TestXpOnApproval:
    async def test_stage_derivation(self):
        assert stage_for_xp(0) == 0
        assert stage_for_xp(99) == 0
        assert stage_for_xp(100) == 1
        assert stage_for_xp(399) == 1
        assert stage_for_xp(400) == 2
        assert stage_for_xp(1000) == 3
        assert stage_for_xp(2000) == 4
        assert stage_for_xp(99999) == 4

    async def test_mandatory_completion_awards_pet_xp(
        self, db, family, mandatory_template_factory
    ):
        from app.services.task_assignment_service import TaskAssignmentService

        kid = await _mk_user(db, family, points=0)
        pet = await _mk_pet(db, kid)
        tmpl = await mandatory_template_factory(family=family, points=10)
        a = TaskAssignment(
            template_id=tmpl.id, family_id=family.id, assigned_to=kid.id,
            assigned_date=date.today(), week_of=date.today(),
            status=AssignmentStatus.PENDING,
        )
        db.add(a)
        await db.commit()

        await TaskAssignmentService.complete_assignment(db, a.id, family.id, kid.id)
        await db.refresh(pet)
        assert pet.xp == XP_PER_MANDATORY

    async def test_gig_auto_approval_awards_pet_xp(
        self, db, family, gig_template_factory
    ):
        from app.core.config import settings
        from app.services.task_assignment_service import TaskAssignmentService

        kid = await _mk_user(db, family, points=0)
        kid.gig_trust_streak = max(1, settings.GIG_AUTO_APPROVE_STREAK)
        await db.commit()
        pet = await _mk_pet(db, kid)
        tmpl = await gig_template_factory(family=family, points=20)
        a = TaskAssignment(
            template_id=tmpl.id, family_id=family.id, assigned_to=kid.id,
            assigned_date=date.today(), week_of=date.today(),
            status=AssignmentStatus.PENDING,
        )
        db.add(a)
        await db.commit()

        await TaskAssignmentService.complete_assignment(
            db, a.id, family.id, kid.id, proof_text="did it"
        )
        await db.refresh(pet)
        assert pet.xp == XP_PER_GIG

    async def test_gig_rejection_awards_no_pet_xp(
        self, db, family, gig_template_factory
    ):
        from app.services.task_assignment_service import TaskAssignmentService

        parent = await _mk_user(db, family, role=UserRole.PARENT)
        kid = await _mk_user(db, family, points=0)
        pet = await _mk_pet(db, kid)
        tmpl = await gig_template_factory(family=family, points=20)
        a = TaskAssignment(
            template_id=tmpl.id, family_id=family.id, assigned_to=kid.id,
            assigned_date=date.today(), week_of=date.today(),
            status=AssignmentStatus.COMPLETED,
            approval_status=ApprovalStatus.PENDING,
            proof_text="tried",
        )
        db.add(a)
        await db.commit()

        await TaskAssignmentService.approve_gig(
            db, a.id, family.id, parent.id, approve=False, notes="redo it"
        )
        await db.refresh(pet)
        assert pet.xp == 0  # rejection must not feed the pet


# ── Level / evolution crossings + notifications ──────────────────────


class TestProgressionNotifications:
    async def test_evolution_crossing_emits_pet_evolved(self, db, family):
        from sqlalchemy import select

        kid = await _mk_user(db, family)
        pet = await _mk_pet(db, kid, xp=95)  # stage 0, just below the 100 gate
        await PetService.on_task_completed(db, kid.id, is_bonus=False)  # +5 → 100
        await db.commit()
        await db.refresh(pet)

        assert pet.xp == 100
        assert pet.evolution_stage == 1
        notes = (
            await db.execute(
                select(Notification).where(Notification.user_id == kid.id)
            )
        ).scalars().all()
        assert any(n.type == NotificationType.PET_EVOLVED for n in notes)

    async def test_level_up_only_emits_pet_level_up(self, db, family):
        from sqlalchemy import select

        kid = await _mk_user(db, family)
        # xp 898 → level 2, stage 2. +5 → 903 → level 3, still stage 2.
        pet = await _mk_pet(db, kid, xp=898)
        assert pet.level == 2 and pet.evolution_stage == 2
        await PetService.on_task_completed(db, kid.id, is_bonus=False)
        await db.commit()
        await db.refresh(pet)

        assert pet.level == 3
        assert pet.evolution_stage == 2  # no evolution this tick
        notes = (
            await db.execute(
                select(Notification).where(Notification.user_id == kid.id)
            )
        ).scalars().all()
        types = {n.type for n in notes}
        assert NotificationType.PET_LEVEL_UP in types
        assert NotificationType.PET_EVOLVED not in types

    async def test_no_crossing_no_notification(self, db, family):
        from sqlalchemy import select

        kid = await _mk_user(db, family)
        await _mk_pet(db, kid, xp=0)  # +5 stays in stage 0 / level 0
        await PetService.on_task_completed(db, kid.id, is_bonus=False)
        await db.commit()
        notes = (
            await db.execute(
                select(Notification).where(Notification.user_id == kid.id)
            )
        ).scalars().all()
        assert notes == []


# ── Care economy (POINTS sink) ───────────────────────────────────────


class TestCareEconomy:
    async def test_play_spends_points_and_boosts_mood(self, db, family):
        kid = await _mk_user(db, family, points=100)
        await _mk_pet(db, kid, mood=50)
        updated = await PetService.care(db, kid.id, "play")
        await db.refresh(kid)
        assert kid.points == 100 - CARE_ACTIONS["play"]["cost"]
        assert updated.mood > 50
        assert len(await _neg_point_txns(db, kid.id)) == 1

    async def test_insufficient_points_rejected(self, db, family):
        kid = await _mk_user(db, family, points=0)
        await _mk_pet(db, kid)
        with pytest.raises(ValidationException):
            await PetService.care(db, kid.id, "play")
        await db.refresh(kid)
        assert kid.points == 0
        assert await _neg_point_txns(db, kid.id) == []

    async def test_feed_when_full_rejects_without_charge(self, db, family):
        kid = await _mk_user(db, family, points=100)
        await _mk_pet(db, kid, hunger=0)
        with pytest.raises(ValidationException):
            await PetService.care(db, kid.id, "feed")
        await db.refresh(kid)
        assert kid.points == 100  # not charged for a wasted feed
        assert await _neg_point_txns(db, kid.id) == []

    async def test_unknown_action_rejected(self, db, family):
        kid = await _mk_user(db, family)
        await _mk_pet(db, kid)
        with pytest.raises(ValidationException):
            await PetService.care(db, kid.id, "teleport")


# ── Cosmetics (stage-gated POINTS sink) ──────────────────────────────


class TestCosmetics:
    async def test_buy_requires_unlock_stage(self, db, family):
        kid = await _mk_user(db, family, points=500)
        await _mk_pet(db, kid, xp=0)  # stage 0
        # hat_cap unlocks at stage 1
        with pytest.raises(ValidationException):
            await PetService.buy_cosmetic(db, kid.id, "hat_cap")
        await db.refresh(kid)
        assert kid.points == 500  # not charged for a locked cosmetic

    async def test_buy_spends_points(self, db, family):
        kid = await _mk_user(db, family, points=100, cash=500)
        await _mk_pet(db, kid, xp=100)  # stage 1
        spec = COSMETICS["hat_cap"]
        rec = await PetService.buy_cosmetic(db, kid.id, "hat_cap")
        await db.refresh(kid)
        assert rec.cosmetic_key == "hat_cap"
        assert rec.equipped is False
        assert kid.points == 100 - spec["price"]
        assert kid.cash_cents == 500  # two-currency: cash untouched
        assert len(await _neg_point_txns(db, kid.id)) == 1

    async def test_duplicate_buy_rejected(self, db, family):
        kid = await _mk_user(db, family, points=200)
        await _mk_pet(db, kid, xp=100)
        await PetService.buy_cosmetic(db, kid.id, "hat_cap")
        with pytest.raises(ValidationException):
            await PetService.buy_cosmetic(db, kid.id, "hat_cap")

    async def test_equip_is_slot_exclusive(self, db, family):
        from sqlalchemy import select

        kid = await _mk_user(db, family, points=300)
        await _mk_pet(db, kid, xp=400)  # stage 2 → both hats unlocked
        await PetService.buy_cosmetic(db, kid.id, "hat_cap")   # slot hat
        await PetService.buy_cosmetic(db, kid.id, "hat_bow")   # slot hat
        await PetService.equip_cosmetic(db, kid.id, "hat_cap")
        await PetService.equip_cosmetic(db, kid.id, "hat_bow")

        rows = {
            r.cosmetic_key: r
            for r in (
                await db.execute(select(PetCosmetic))
            ).scalars().all()
        }
        assert rows["hat_bow"].equipped is True
        assert rows["hat_cap"].equipped is False  # unequipped by same-slot swap

    async def test_equip_unowned_rejected(self, db, family):
        kid = await _mk_user(db, family, points=300)
        await _mk_pet(db, kid, xp=400)
        with pytest.raises(ValidationException):
            await PetService.equip_cosmetic(db, kid.id, "hat_cap")

    async def test_list_cosmetics_annotates_state(self, db, family):
        kid = await _mk_user(db, family, points=25)
        await _mk_pet(db, kid, xp=100)  # stage 1
        data = await PetService.list_cosmetics(db, kid.id)
        by_key = {c["key"]: c for c in data["cosmetics"]}
        assert by_key["hat_cap"]["unlocked"] is True    # stage 1 >= 1
        assert by_key["hat_cap"]["affordable"] is True  # 25 >= 20
        assert by_key["hat_crown"]["unlocked"] is False  # needs stage 3


# ── Quest view (read-only) ───────────────────────────────────────────


class TestQuestView:
    async def test_returns_today_quests_and_pet_state(
        self, db, family, mandatory_template_factory
    ):
        from app.services.task_assignment_service import TaskAssignmentService

        kid = await _mk_user(db, family)
        await _mk_pet(db, kid, xp=100)
        today = await TaskAssignmentService._user_local_today(db, kid.id)
        tmpl = await mandatory_template_factory(family=family, points=10)
        a = TaskAssignment(
            template_id=tmpl.id, family_id=family.id, assigned_to=kid.id,
            assigned_date=today, week_of=today,
            status=AssignmentStatus.PENDING,
        )
        db.add(a)
        await db.commit()

        view = await PetService.quest_view(db, kid.id, family.id)
        assert view["pet"] is not None
        assert view["pet"]["evolution_stage"] == 1
        assert "equipped_cosmetics" in view["pet"]
        assert len(view["quests"]) == 1
        q = view["quests"][0]
        assert q["title"] == tmpl.title
        assert q["pet_xp_reward"] == XP_PER_MANDATORY
        assert q["done"] is False


# ── Isolation (per-kid + family) ─────────────────────────────────────


class TestIsolation:
    async def test_kid_cannot_act_on_sibling(self, db, family):
        kid_a = await _mk_user(db, family)
        kid_b = await _mk_user(db, family)
        with pytest.raises(ForbiddenException):
            await PetService.resolve_target(db, kid_a, kid_b.id, action=True)

    async def test_kid_cannot_view_sibling(self, db, family):
        kid_a = await _mk_user(db, family)
        kid_b = await _mk_user(db, family)
        with pytest.raises(ForbiddenException):
            await PetService.resolve_target(db, kid_a, kid_b.id, action=False)

    async def test_parent_can_view_kid(self, db, family):
        parent = await _mk_user(db, family, role=UserRole.PARENT)
        kid = await _mk_user(db, family)
        resolved = await PetService.resolve_target(
            db, parent, kid.id, action=False
        )
        assert resolved == kid.id

    async def test_parent_cannot_act_on_kid(self, db, family):
        parent = await _mk_user(db, family, role=UserRole.PARENT)
        kid = await _mk_user(db, family)
        with pytest.raises(ForbiddenException):
            await PetService.resolve_target(db, parent, kid.id, action=True)

    async def test_cross_family_view_forbidden(self, db, family, other_family):
        parent = await _mk_user(db, family, role=UserRole.PARENT)
        outsider = await _mk_user(db, other_family)
        with pytest.raises(ForbiddenException):
            await PetService.resolve_target(
                db, parent, outsider.id, action=False
            )

    async def test_care_affects_only_actor_pet(self, db, family):
        kid_a = await _mk_user(db, family, points=100)
        kid_b = await _mk_user(db, family, points=100)
        pet_a = await _mk_pet(db, kid_a, mood=40)
        pet_b = await _mk_pet(db, kid_b, mood=40)
        await PetService.care(db, kid_a.id, "play")
        await db.refresh(pet_a)
        await db.refresh(pet_b)
        await db.refresh(kid_b)
        assert pet_a.mood > 40      # actor's pet changed
        assert pet_b.mood == 40     # sibling's pet untouched
        assert kid_b.points == 100  # sibling's points untouched


# ── Two-currency guard ───────────────────────────────────────────────


class TestTwoCurrencyGuard:
    async def test_care_never_touches_cash(self, db, family):
        kid = await _mk_user(db, family, points=50, cash=777)
        await _mk_pet(db, kid)
        await PetService.care(db, kid.id, "play")
        await db.refresh(kid)
        assert kid.cash_cents == 777
        assert kid.points == 50 - CARE_ACTIONS["play"]["cost"]

    async def test_cosmetic_never_touches_cash(self, db, family):
        from sqlalchemy import select
        from app.models.cash_transaction import CashTransaction

        kid = await _mk_user(db, family, points=100, cash=1234)
        await _mk_pet(db, kid, xp=100)
        await PetService.buy_cosmetic(db, kid.id, "hat_cap")
        await db.refresh(kid)
        assert kid.cash_cents == 1234  # cash never moves
        assert kid.points < 100        # points are the only sink
        cash_txns = (
            await db.execute(
                select(CashTransaction).where(CashTransaction.user_id == kid.id)
            )
        ).scalars().all()
        assert cash_txns == []


@pytest.mark.asyncio
async def test_pet_hook_failure_is_best_effort(db, family, mandatory_template_factory, monkeypatch):
    """Regression (pet review MAJOR): a throw inside the pet XP hook must NOT
    roll back the surrounding point award / approval. on_task_completed
    swallows the failure; the kid still gets their points and the assignment
    still completes."""
    from app.services.task_assignment_service import TaskAssignmentService
    from app.services.pet_service import PetService

    kid = await _mk_user(db, family, points=0)
    await _mk_pet(db, kid)
    tmpl = await mandatory_template_factory(family=family, points=10)
    a = TaskAssignment(
        template_id=tmpl.id, family_id=family.id, assigned_to=kid.id,
        assigned_date=date.today(), week_of=date.today(),
        status=AssignmentStatus.PENDING,
    )
    db.add(a)
    await db.commit()

    async def _boom(*args, **kwargs):
        raise RuntimeError("pet exploded")

    monkeypatch.setattr(PetService, "_apply_task_reward", _boom)

    # Must not raise despite the pet hook throwing.
    await TaskAssignmentService.complete_assignment(db, a.id, family.id, kid.id)

    await db.refresh(kid)
    await db.refresh(a)
    assert kid.points == 10                     # points survived the pet failure
    assert a.status == AssignmentStatus.COMPLETED
