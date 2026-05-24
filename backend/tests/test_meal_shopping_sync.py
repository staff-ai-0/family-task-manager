"""Meal → shopping ingredient sync (W7.4)."""

import pytest
from datetime import date

from app.schemas.meal import MealPlanEntryCreate, RecipeCreate
from app.schemas.shopping import ShoppingListCreate
from app.services.meal_service import (
    MealService,
    _parse_ingredient_lines,
)
from app.services.shopping_service import ShoppingService


class TestParseLines:
    def test_blank(self):
        assert _parse_ingredient_lines("") == []
        assert _parse_ingredient_lines("   \n  ") == []

    def test_strips_bullets(self):
        out = _parse_ingredient_lines(
            "- 2 cups flour\n* 1 tsp salt\n• 3 eggs"
        )
        assert out == ["2 cups flour", "1 tsp salt", "3 eggs"]

    def test_strips_numbering(self):
        out = _parse_ingredient_lines(
            "1. Onion\n2) Garlic\n3. Olive oil"
        )
        assert out == ["Onion", "Garlic", "Olive oil"]

    def test_skips_blank_lines(self):
        out = _parse_ingredient_lines("Item A\n\n\nItem B\n")
        assert out == ["Item A", "Item B"]


class TestAutoShop:
    async def test_no_recipe_no_shop_writes(
        self, db_session, test_family, test_parent_user
    ):
        await ShoppingService.create_list(
            db_session, ShoppingListCreate(name="Costco"),
            test_family.id, test_parent_user.id,
        )
        await MealService.add_entry(
            db_session,
            MealPlanEntryCreate(
                plan_date=date.today(), meal_type="lunch", title="Sandwich"
            ),
            test_family.id,
            auto_shop=True,
            added_by=test_parent_user.id,
        )
        lists = await ShoppingService.list_lists(db_session, test_family.id)
        costco = next(l for l in lists if l["obj"].name == "Costco")
        assert costco["item_count"] == 0

    async def test_recipe_fans_out_ingredients(
        self, db_session, test_family, test_parent_user
    ):
        r = await MealService.create_recipe(
            db_session,
            RecipeCreate(
                name="Pasta",
                ingredients_text="- 200g spaghetti\n- 2 tomatoes\n- garlic\n",
            ),
            test_family.id,
            test_parent_user.id,
        )
        lst = await ShoppingService.create_list(
            db_session, ShoppingListCreate(name="Mercado"),
            test_family.id, test_parent_user.id,
        )
        await MealService.add_entry(
            db_session,
            MealPlanEntryCreate(
                plan_date=date.today(),
                meal_type="dinner",
                title="Pasta night",
                recipe_id=r.id,
            ),
            test_family.id,
            auto_shop=True,
            added_by=test_parent_user.id,
        )
        rows = await ShoppingService.list_lists(db_session, test_family.id)
        mercado = next(l for l in rows if l["obj"].name == "Mercado")
        assert mercado["item_count"] == 3

    async def test_recipe_creates_default_list_when_none(
        self, db_session, test_family, test_parent_user
    ):
        r = await MealService.create_recipe(
            db_session,
            RecipeCreate(name="Eggs", ingredients_text="- 3 eggs\n- butter"),
            test_family.id, test_parent_user.id,
        )
        await MealService.add_entry(
            db_session,
            MealPlanEntryCreate(
                plan_date=date.today(),
                meal_type="breakfast",
                title="Scramble",
                recipe_id=r.id,
            ),
            test_family.id,
            auto_shop=True,
            added_by=test_parent_user.id,
        )
        rows = await ShoppingService.list_lists(db_session, test_family.id)
        names = [l["obj"].name for l in rows]
        assert "Meal prep" in names
        meal_prep = next(l for l in rows if l["obj"].name == "Meal prep")
        assert meal_prep["item_count"] == 2

    async def test_auto_shop_false_does_nothing(
        self, db_session, test_family, test_parent_user
    ):
        r = await MealService.create_recipe(
            db_session,
            RecipeCreate(name="X", ingredients_text="- A\n- B"),
            test_family.id, test_parent_user.id,
        )
        await ShoppingService.create_list(
            db_session, ShoppingListCreate(name="L"),
            test_family.id, test_parent_user.id,
        )
        await MealService.add_entry(
            db_session,
            MealPlanEntryCreate(
                plan_date=date.today(), meal_type="lunch", title="Lunch",
                recipe_id=r.id,
            ),
            test_family.id,
            auto_shop=False,
            added_by=test_parent_user.id,
        )
        rows = await ShoppingService.list_lists(db_session, test_family.id)
        l = next(x for x in rows if x["obj"].name == "L")
        assert l["item_count"] == 0
