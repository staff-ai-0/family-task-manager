"""MCP adapters for the meals domain.

Migrated from the legacy ``add_recipe`` + ``schedule_meal`` handlers.
"""

from datetime import date as date_t
from uuid import UUID

from app.mcp.adapters import ServiceAdapter
from app.mcp.context import McpContext
from app.models.meal import MealPlanEntry, Recipe


def _ser_recipe(r: Recipe) -> dict:
    return {"id": str(r.id), "name": r.name, "prep_minutes": r.prep_minutes}


def _ser_entry(e: MealPlanEntry) -> dict:
    return {
        "id": str(e.id),
        "plan_date": e.plan_date.isoformat() if e.plan_date else None,
        "meal_type": e.meal_type,
        "title": e.title,
    }


class RecipeAdapter(ServiceAdapter):
    async def list(self, ctx: McpContext) -> list[dict]:
        from app.services.meal_service import MealService

        rows = await MealService.list_recipes(ctx.db, ctx.family_id)
        return [_ser_recipe(r) for r in rows]

    async def get(self, ctx: McpContext, entity_id: UUID) -> dict:
        from app.services.meal_service import MealService

        return _ser_recipe(await MealService.get_recipe(ctx.db, entity_id, ctx.family_id))

    async def create(self, ctx: McpContext, data: dict) -> dict:
        from app.schemas.meal import RecipeCreate
        from app.services.meal_service import MealService

        payload = RecipeCreate(
            name=str(data["name"])[:200],
            description=data.get("description"),
            ingredients_text=data.get("ingredients_text"),
            prep_minutes=(int(data["prep_minutes"]) if data.get("prep_minutes") else None),
            source_url=data.get("source_url"),
        )
        r = await MealService.create_recipe(ctx.db, payload, ctx.family_id, ctx.user_id)
        return _ser_recipe(r)

    async def update(self, ctx: McpContext, entity_id: UUID, data: dict) -> dict:
        from app.schemas.meal import RecipeUpdate
        from app.services.meal_service import MealService

        r = await MealService.update_recipe(
            ctx.db, entity_id, RecipeUpdate(**data), ctx.family_id
        )
        return _ser_recipe(r)

    async def delete(self, ctx: McpContext, entity_id: UUID) -> None:
        from app.services.meal_service import MealService

        await MealService.delete_recipe(ctx.db, entity_id, ctx.family_id)


class PlanEntryAdapter(ServiceAdapter):
    async def list(self, ctx: McpContext) -> list[dict]:
        """Return all plan entries for the family (up to 90 days back)."""
        from datetime import timedelta, date as _date
        from app.services.meal_service import MealService

        today = _date.today()
        rows = await MealService.list_plan(
            ctx.db,
            ctx.family_id,
            start=today - timedelta(days=30),
            end=today + timedelta(days=90),
        )
        return [_ser_entry(e) for e in rows]

    async def get(self, ctx: McpContext, entity_id: UUID) -> dict:
        from sqlalchemy import and_, select
        from app.models.meal import MealPlanEntry

        q = select(MealPlanEntry).where(
            and_(
                MealPlanEntry.id == entity_id,
                MealPlanEntry.family_id == ctx.family_id,
            )
        )
        e = (await ctx.db.execute(q)).scalar_one_or_none()
        if not e:
            raise ValueError(f"Meal plan entry {entity_id} not found")
        return _ser_entry(e)

    async def create(self, ctx: McpContext, data: dict) -> dict:
        from app.schemas.meal import MealPlanEntryCreate
        from app.services.meal_service import MealService

        payload = MealPlanEntryCreate(
            plan_date=date_t.fromisoformat(data["plan_date"]),
            meal_type=str(data["meal_type"]),
            title=str(data["title"])[:200],
            recipe_id=(UUID(data["recipe_id"]) if data.get("recipe_id") else None),
            notes=data.get("notes"),
        )
        e = await MealService.add_entry(ctx.db, payload, ctx.family_id, added_by=ctx.user_id)
        return _ser_entry(e)

    async def update(self, ctx: McpContext, entity_id: UUID, data: dict) -> dict:
        from app.schemas.meal import MealPlanEntryUpdate
        from app.services.meal_service import MealService

        e = await MealService.update_entry(
            ctx.db, entity_id, MealPlanEntryUpdate(**data), ctx.family_id
        )
        return _ser_entry(e)

    async def delete(self, ctx: McpContext, entity_id: UUID) -> None:
        from app.services.meal_service import MealService

        await MealService.delete_entry(ctx.db, entity_id, ctx.family_id)
