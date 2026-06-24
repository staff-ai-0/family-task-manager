"""MCP adapters for the shopping domain.

Migrated from the legacy ``add_shopping_item`` handler: adds an item to the
family's most recent active list, creating a 'Quick list' if none exists.
"""

from uuid import UUID

from sqlalchemy import and_, select

from app.mcp.adapters import ServiceAdapter
from app.mcp.context import McpContext
from app.models.shopping import ShoppingItem, ShoppingList


def _ser_item(item: ShoppingItem, list_name: str) -> dict:
    return {
        "id": str(item.id),
        "name": item.name,
        "qty": item.qty,
        "list_name": list_name,
    }


class ItemAdapter(ServiceAdapter):
    async def list(self, ctx: McpContext) -> list[dict]:
        q = (
            select(ShoppingItem, ShoppingList.name)
            .join(ShoppingList, ShoppingList.id == ShoppingItem.list_id)
            .where(ShoppingList.family_id == ctx.family_id)
            .order_by(ShoppingItem.created_at.desc())
            .limit(100)
        )
        rows = (await ctx.db.execute(q)).all()
        return [_ser_item(item, name) for item, name in rows]

    async def create(self, ctx: McpContext, data: dict) -> dict:
        from app.schemas.shopping import ShoppingItemCreate, ShoppingListCreate
        from app.services.shopping_service import ShoppingService

        lst_q = (
            select(ShoppingList)
            .where(
                and_(
                    ShoppingList.family_id == ctx.family_id,
                    ShoppingList.is_archived.is_(False),
                )
            )
            .order_by(ShoppingList.updated_at.desc())
            .limit(1)
        )
        lst = (await ctx.db.execute(lst_q)).scalar_one_or_none()
        if lst is None:
            lst = await ShoppingService.create_list(
                ctx.db, ShoppingListCreate(name="Quick list"), ctx.family_id, ctx.user_id
            )
        item = await ShoppingService.add_item(
            ctx.db,
            list_id=lst.id,
            family_id=ctx.family_id,
            added_by=ctx.user_id,
            data=ShoppingItemCreate(
                name=str(data["name"])[:200],
                qty=data.get("qty"),
            ),
        )
        return _ser_item(item, lst.name)

    async def update(self, ctx: McpContext, entity_id: UUID, data: dict) -> dict:
        from app.schemas.shopping import ShoppingItemUpdate
        from app.services.shopping_service import ShoppingService

        item = await ShoppingService.update_item(
            ctx.db,
            item_id=entity_id,
            family_id=ctx.family_id,
            actor_id=ctx.user_id,
            data=ShoppingItemUpdate(**data),
        )
        # list name not needed for the update echo
        return {"id": str(item.id), "name": item.name, "qty": item.qty}

    async def delete(self, ctx: McpContext, entity_id: UUID) -> None:
        from app.services.shopping_service import ShoppingService

        await ShoppingService.delete_item(ctx.db, item_id=entity_id, family_id=ctx.family_id)
