"""Pet treats (W5.4) — kid burns points for pet stat boosts."""

import pytest

from app.core.exceptions import NotFoundException, ValidationException
from app.services.pet_service import PetService, TREATS


class TestTreats:
    async def test_catalog_shape(self):
        for key, t in TREATS.items():
            assert "cost" in t and t["cost"] > 0
            assert "hunger" in t
            assert "mood" in t
            assert "xp" in t

    async def test_unknown_treat_rejected(
        self, db_session, test_child_user
    ):
        await PetService.create_for_user(
            db_session, test_child_user.id, "X", "cat"
        )
        with pytest.raises(ValidationException):
            await PetService.give_treat(
                db_session, test_child_user.id, "diamonds"
            )

    async def test_insufficient_points_rejected(
        self, db_session, test_child_user
    ):
        await PetService.create_for_user(
            db_session, test_child_user.id, "X", "cat"
        )
        test_child_user.points = 0
        await db_session.commit()
        with pytest.raises(ValidationException):
            await PetService.give_treat(db_session, test_child_user.id, "snack")

    async def test_snack_deducts_and_applies(
        self, db_session, test_child_user
    ):
        pet = await PetService.create_for_user(
            db_session, test_child_user.id, "X", "cat"
        )
        # ensure ample points + known starting hunger
        test_child_user.points = 100
        pet.hunger = 50
        pet.mood = 50
        pet.xp = 0
        await db_session.commit()

        updated = await PetService.give_treat(
            db_session, test_child_user.id, "snack"
        )
        snack = TREATS["snack"]
        await db_session.refresh(test_child_user)
        assert test_child_user.points == 100 - snack["cost"]
        assert updated.hunger == max(0, 50 + snack["hunger"])
        assert updated.mood == min(100, 50 + snack["mood"])

    async def test_vitamin_grants_xp(
        self, db_session, test_child_user
    ):
        await PetService.create_for_user(
            db_session, test_child_user.id, "X", "cat"
        )
        test_child_user.points = 100
        await db_session.commit()
        before = test_child_user.points
        updated = await PetService.give_treat(
            db_session, test_child_user.id, "vitamin"
        )
        assert updated.xp >= TREATS["vitamin"]["xp"]
        await db_session.refresh(test_child_user)
        assert test_child_user.points == before - TREATS["vitamin"]["cost"]

    async def test_treat_without_pet_404(
        self, db_session, test_child_user
    ):
        test_child_user.points = 100
        await db_session.commit()
        with pytest.raises(NotFoundException):
            await PetService.give_treat(
                db_session, test_child_user.id, "snack"
            )
