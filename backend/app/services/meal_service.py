"""Meal planning service (W7.2)."""

from datetime import date as date_t
from typing import List, Optional
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.models.meal import MealPlanEntry, Recipe
from app.models.shopping import ShoppingList
from app.schemas.meal import (
    MealPlanEntryCreate,
    MealPlanEntryUpdate,
    RecipeCreate,
    RecipeUpdate,
)


import re as _re
_NUMBERING_RE = _re.compile(r"^\d{1,3}[.)]\s+")

# Leading qty token: digits (optional decimal/fraction) + optional unit word.
_QTY_RE = _re.compile(
    r"^(\d+(?:[./,]\d+)?\s*[A-Za-zÁÉÍÓÚÑáéíóúñ]{0,8})\s+(.+)$"
)


def _parse_ingredient_lines(text: str) -> list[str]:
    """Split free-form ingredient text into normalized item names.

    Handles bullet markers ("- ", "* ", "• ") and numbering ("1. ", "2) ").
    Quantities like "200g flour" or "2 cups flour" are preserved — only
    explicit list markers are stripped.
    """
    if not text:
        return []
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        while line and line[0] in "-*•·":
            line = line[1:].lstrip()
        line = _NUMBERING_RE.sub("", line)
        line = line.strip()
        if line:
            out.append(line[:200])
    return out


def _split_qty(line: str) -> tuple[str | None, str]:
    """Best-effort split of "200g flour" → ("200g", "flour").

    Returns (qty, name). qty=None when no leading number detected.
    """
    if not line:
        return None, ""
    m = _QTY_RE.match(line)
    if m:
        qty = m.group(1).strip()
        name = m.group(2).strip()
        if name:
            return qty[:40], name[:200]
    return None, line[:200]


class MealService:
    # ─── Recipes ──────────────────────────────────────────────────────

    @staticmethod
    async def list_recipes(
        db: AsyncSession, family_id: UUID
    ) -> List[Recipe]:
        q = (
            select(Recipe)
            .where(Recipe.family_id == family_id)
            .order_by(Recipe.name.asc())
        )
        return list((await db.execute(q)).scalars().all())

    @staticmethod
    async def get_recipe(
        db: AsyncSession, recipe_id: UUID, family_id: UUID
    ) -> Recipe:
        q = select(Recipe).where(
            and_(Recipe.id == recipe_id, Recipe.family_id == family_id)
        )
        r = (await db.execute(q)).scalar_one_or_none()
        if not r:
            raise NotFoundException("Recipe not found")
        return r

    @staticmethod
    async def create_recipe(
        db: AsyncSession,
        data: RecipeCreate,
        family_id: UUID,
        created_by: UUID,
    ) -> Recipe:
        r = Recipe(
            family_id=family_id,
            name=data.name,
            description=data.description,
            ingredients_text=data.ingredients_text,
            prep_minutes=data.prep_minutes,
            source_url=data.source_url,
            created_by=created_by,
        )
        db.add(r)
        await db.commit()
        await db.refresh(r)
        return r

    @staticmethod
    async def update_recipe(
        db: AsyncSession,
        recipe_id: UUID,
        data: RecipeUpdate,
        family_id: UUID,
    ) -> Recipe:
        r = await MealService.get_recipe(db, recipe_id, family_id)
        for k, v in data.model_dump(exclude_unset=True).items():
            setattr(r, k, v)
        await db.commit()
        await db.refresh(r)
        return r

    @staticmethod
    async def delete_recipe(
        db: AsyncSession, recipe_id: UUID, family_id: UUID
    ) -> None:
        r = await MealService.get_recipe(db, recipe_id, family_id)
        await db.delete(r)
        await db.commit()

    # ─── Meal plan entries ────────────────────────────────────────────

    @staticmethod
    async def list_plan(
        db: AsyncSession,
        family_id: UUID,
        start: date_t,
        end: date_t,
    ) -> List[MealPlanEntry]:
        q = (
            select(MealPlanEntry)
            .where(
                and_(
                    MealPlanEntry.family_id == family_id,
                    MealPlanEntry.plan_date >= start,
                    MealPlanEntry.plan_date <= end,
                )
            )
            .order_by(MealPlanEntry.plan_date.asc())
        )
        return list((await db.execute(q)).scalars().all())

    @staticmethod
    async def add_entry(
        db: AsyncSession,
        data: MealPlanEntryCreate,
        family_id: UUID,
        *,
        auto_shop: bool = False,
        added_by: Optional[UUID] = None,
    ) -> MealPlanEntry:
        # If recipe_id given, verify it belongs to this family.
        recipe: Optional[Recipe] = None
        if data.recipe_id is not None:
            recipe = await MealService.get_recipe(db, data.recipe_id, family_id)
        e = MealPlanEntry(
            family_id=family_id,
            plan_date=data.plan_date,
            meal_type=data.meal_type,
            recipe_id=data.recipe_id,
            title=data.title,
            notes=data.notes,
        )
        db.add(e)
        await db.commit()
        await db.refresh(e)

        if auto_shop and recipe and recipe.ingredients_text:
            await MealService._sync_ingredients_to_shopping(
                db, family_id, recipe, added_by or family_id
            )
        return e

    @staticmethod
    async def _sync_ingredients_to_shopping(
        db: AsyncSession,
        family_id: UUID,
        recipe: Recipe,
        added_by: UUID,
    ) -> list[str]:
        """Push recipe ingredients onto the family's most-recent active list."""
        from app.schemas.shopping import ShoppingItemCreate, ShoppingListCreate
        from app.services.shopping_service import ShoppingService

        lines = _parse_ingredient_lines(recipe.ingredients_text or "")
        if not lines:
            return []

        lst_q = (
            select(ShoppingList)
            .where(
                and_(
                    ShoppingList.family_id == family_id,
                    ShoppingList.is_archived.is_(False),
                )
            )
            .order_by(ShoppingList.updated_at.desc())
            .limit(1)
        )
        lst = (await db.execute(lst_q)).scalar_one_or_none()
        if lst is None:
            lst = await ShoppingService.create_list(
                db,
                ShoppingListCreate(name="Meal prep"),
                family_id,
                added_by,
            )

        added: list[str] = []
        for line in lines:
            qty, name = _split_qty(line)
            await ShoppingService.add_item(
                db,
                list_id=lst.id,
                family_id=family_id,
                added_by=added_by,
                data=ShoppingItemCreate(name=name, qty=qty),
            )
            added.append(line)
        return added

    @staticmethod
    async def update_entry(
        db: AsyncSession,
        entry_id: UUID,
        data: MealPlanEntryUpdate,
        family_id: UUID,
    ) -> MealPlanEntry:
        q = select(MealPlanEntry).where(
            and_(
                MealPlanEntry.id == entry_id,
                MealPlanEntry.family_id == family_id,
            )
        )
        e = (await db.execute(q)).scalar_one_or_none()
        if not e:
            raise NotFoundException("Meal entry not found")
        update = data.model_dump(exclude_unset=True)
        if update.get("recipe_id") is not None:
            await MealService.get_recipe(db, update["recipe_id"], family_id)
        for k, v in update.items():
            setattr(e, k, v)
        await db.commit()
        await db.refresh(e)
        return e

    @staticmethod
    async def delete_entry(
        db: AsyncSession, entry_id: UUID, family_id: UUID
    ) -> None:
        q = select(MealPlanEntry).where(
            and_(
                MealPlanEntry.id == entry_id,
                MealPlanEntry.family_id == family_id,
            )
        )
        e = (await db.execute(q)).scalar_one_or_none()
        if not e:
            raise NotFoundException("Meal entry not found")
        await db.delete(e)
        await db.commit()
