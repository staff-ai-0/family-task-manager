"""KidPet service tests (W4.3)."""

import pytest
from datetime import datetime, timedelta, timezone

from app.core.exceptions import NotFoundException, ValidationException
from app.models.kid_pet import KidPet
from app.services.pet_service import PetService


class TestPetCreation:
    async def test_create_pet(self, db_session, test_child_user):
        pet = await PetService.create_for_user(
            db_session, test_child_user.id, "Whiskers", "cat"
        )
        assert pet.name == "Whiskers"
        assert pet.species == "cat"
        assert pet.mood == 80
        assert pet.hunger == 50
        assert pet.xp == 0

    async def test_duplicate_pet_rejected(self, db_session, test_child_user):
        await PetService.create_for_user(
            db_session, test_child_user.id, "A", "cat"
        )
        with pytest.raises(ValidationException):
            await PetService.create_for_user(
                db_session, test_child_user.id, "B", "dog"
            )

    async def test_invalid_species_rejected(self, db_session, test_child_user):
        with pytest.raises(ValidationException):
            await PetService.create_for_user(
                db_session, test_child_user.id, "X", "rhino"
            )

    async def test_blank_name_rejected(self, db_session, test_child_user):
        with pytest.raises(ValidationException):
            await PetService.create_for_user(
                db_session, test_child_user.id, "   ", "cat"
            )


class TestLevelDerivation:
    def test_level_from_xp(self):
        for xp, expected in [(0, 0), (99, 0), (100, 1), (399, 1), (400, 2), (900, 3)]:
            p = KidPet(xp=xp)
            assert p.level == expected, f"xp={xp} → expected level {expected}"

    def test_xp_to_next_level(self):
        p = KidPet(xp=150)
        # level 1 → next level 2, requires 400 xp
        assert p.level == 1
        assert p.xp_to_next_level == 400


class TestDecay:
    def test_no_decay_within_24h(self, db_session, test_child_user):
        pet = KidPet(
            user_id=test_child_user.id, name="X", species="cat",
            mood=80, hunger=20,
            last_decay_at=datetime.now(timezone.utc),
        )
        PetService.apply_decay_in_place(pet)
        assert pet.mood == 80
        assert pet.hunger == 20

    def test_one_day_decay(self, test_child_user):
        old = datetime.now(timezone.utc) - timedelta(days=1, hours=1)
        pet = KidPet(
            user_id=test_child_user.id, name="X", species="cat",
            mood=80, hunger=20, last_decay_at=old,
        )
        PetService.apply_decay_in_place(pet)
        assert pet.hunger == 40  # 20 + 20
        assert pet.mood == 65   # 80 - 15

    def test_decay_clamped(self, test_child_user):
        old = datetime.now(timezone.utc) - timedelta(days=20)
        pet = KidPet(
            user_id=test_child_user.id, name="X", species="cat",
            mood=10, hunger=90, last_decay_at=old,
        )
        PetService.apply_decay_in_place(pet)
        assert pet.hunger == 100
        assert pet.mood == 0


class TestFeedAndPlay:
    async def test_feed_lowers_hunger(self, db_session, test_child_user):
        await PetService.create_for_user(db_session, test_child_user.id, "X", "cat")
        pet = await PetService.feed(db_session, test_child_user.id)
        assert pet.hunger < 50

    async def test_feed_when_full_rejects(self, db_session, test_child_user):
        pet = await PetService.create_for_user(
            db_session, test_child_user.id, "X", "cat"
        )
        pet.hunger = 0
        await db_session.commit()
        with pytest.raises(ValidationException):
            await PetService.feed(db_session, test_child_user.id)

    async def test_play_raises_mood(self, db_session, test_child_user):
        pet = await PetService.create_for_user(
            db_session, test_child_user.id, "X", "cat"
        )
        pet.mood = 50
        await db_session.commit()
        updated = await PetService.play(db_session, test_child_user.id)
        assert updated.mood > 50


class TestTaskHook:
    async def test_no_pet_is_noop(self, db_session, test_child_user):
        # Should not raise
        await PetService.on_task_completed(
            db_session, test_child_user.id, is_bonus=False
        )

    async def test_mandatory_gives_5_xp(self, db_session, test_child_user):
        pet = await PetService.create_for_user(
            db_session, test_child_user.id, "X", "cat"
        )
        await PetService.on_task_completed(
            db_session, test_child_user.id, is_bonus=False
        )
        await db_session.commit()
        await db_session.refresh(pet)
        assert pet.xp == 5

    async def test_gig_gives_20_xp(self, db_session, test_child_user):
        pet = await PetService.create_for_user(
            db_session, test_child_user.id, "X", "cat"
        )
        await PetService.on_task_completed(
            db_session, test_child_user.id, is_bonus=True
        )
        await db_session.commit()
        await db_session.refresh(pet)
        assert pet.xp == 20
