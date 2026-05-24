"""Meal planning service tests (W7.2)."""

import pytest
from datetime import date, timedelta
from uuid import uuid4

from app.core.exceptions import NotFoundException
from app.schemas.meal import (
    MealPlanEntryCreate,
    MealPlanEntryUpdate,
    RecipeCreate,
    RecipeUpdate,
)
from app.services.meal_service import MealService


class TestRecipes:
    async def test_create_and_get(
        self, db_session, test_family, test_parent_user
    ):
        r = await MealService.create_recipe(
            db_session,
            RecipeCreate(name="Tacos al pastor", prep_minutes=30),
            test_family.id,
            test_parent_user.id,
        )
        assert r.name == "Tacos al pastor"
        assert r.prep_minutes == 30
        fetched = await MealService.get_recipe(db_session, r.id, test_family.id)
        assert fetched.id == r.id

    async def test_isolation(self, db_session, test_family, test_parent_user):
        r = await MealService.create_recipe(
            db_session,
            RecipeCreate(name="A"),
            test_family.id,
            test_parent_user.id,
        )
        with pytest.raises(NotFoundException):
            await MealService.get_recipe(db_session, r.id, uuid4())

    async def test_update_recipe(
        self, db_session, test_family, test_parent_user
    ):
        r = await MealService.create_recipe(
            db_session,
            RecipeCreate(name="Old"),
            test_family.id,
            test_parent_user.id,
        )
        updated = await MealService.update_recipe(
            db_session, r.id, RecipeUpdate(name="New", prep_minutes=45),
            test_family.id,
        )
        assert updated.name == "New"
        assert updated.prep_minutes == 45


class TestMealPlan:
    async def test_add_entry_free_text(
        self, db_session, test_family, test_parent_user
    ):
        e = await MealService.add_entry(
            db_session,
            MealPlanEntryCreate(
                plan_date=date.today(),
                meal_type="lunch",
                title="Leftovers",
            ),
            test_family.id,
        )
        assert e.title == "Leftovers"
        assert e.recipe_id is None

    async def test_add_entry_with_recipe(
        self, db_session, test_family, test_parent_user
    ):
        r = await MealService.create_recipe(
            db_session,
            RecipeCreate(name="Soup"),
            test_family.id,
            test_parent_user.id,
        )
        e = await MealService.add_entry(
            db_session,
            MealPlanEntryCreate(
                plan_date=date.today(),
                meal_type="dinner",
                title="Soup night",
                recipe_id=r.id,
            ),
            test_family.id,
        )
        assert e.recipe_id == r.id

    async def test_recipe_from_other_family_rejected(
        self, db_session, test_family, test_parent_user
    ):
        from uuid import uuid4
        with pytest.raises(NotFoundException):
            await MealService.add_entry(
                db_session,
                MealPlanEntryCreate(
                    plan_date=date.today(),
                    meal_type="lunch",
                    title="X",
                    recipe_id=uuid4(),
                ),
                test_family.id,
            )

    async def test_invalid_meal_type_rejected(
        self, db_session, test_family, test_parent_user
    ):
        with pytest.raises(Exception):
            MealPlanEntryCreate(
                plan_date=date.today(),
                meal_type="brunch",
                title="X",
            )

    async def test_range_filter(
        self, db_session, test_family, test_parent_user
    ):
        today = date.today()
        await MealService.add_entry(
            db_session,
            MealPlanEntryCreate(plan_date=today, meal_type="breakfast", title="Today"),
            test_family.id,
        )
        await MealService.add_entry(
            db_session,
            MealPlanEntryCreate(
                plan_date=today + timedelta(days=10),
                meal_type="lunch",
                title="Later",
            ),
            test_family.id,
        )
        rows = await MealService.list_plan(
            db_session, test_family.id, today, today + timedelta(days=3)
        )
        titles = [r.title for r in rows]
        assert "Today" in titles
        assert "Later" not in titles

    async def test_delete_entry(
        self, db_session, test_family, test_parent_user
    ):
        e = await MealService.add_entry(
            db_session,
            MealPlanEntryCreate(
                plan_date=date.today(), meal_type="dinner", title="Drop"
            ),
            test_family.id,
        )
        await MealService.delete_entry(db_session, e.id, test_family.id)
        with pytest.raises(NotFoundException):
            await MealService.update_entry(
                db_session, e.id, MealPlanEntryUpdate(title="X"), test_family.id
            )
