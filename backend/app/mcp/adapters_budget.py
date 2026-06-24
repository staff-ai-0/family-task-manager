from uuid import UUID

from app.mcp.adapters import ServiceAdapter
from app.mcp.context import McpContext
from app.services.budget.account_service import AccountService
from app.schemas.budget import (
    AccountCreate as AppAccountCreate,
    AccountUpdate as AppAccountUpdate,
)
from app.models.budget import BudgetAccount


def _ser(a: BudgetAccount) -> dict:
    """Serialize a BudgetAccount to a JSON-safe dict for tool output.

    Exposes ``account_type`` (the MCP-facing name) which maps to the model's
    ``type`` column.
    """
    return {"id": str(a.id), "name": a.name, "account_type": a.type}


class AccountAdapter(ServiceAdapter):
    """Binds the generic CRUD ops to the real AccountService.

    AccountService subclasses BaseFamilyService[BudgetAccount], so get/delete
    route through the inherited family-scoped classmethods. create/update take
    the app-layer pydantic schemas, so we translate the MCP ``account_type``
    field to the model's ``type`` field here.
    """

    async def list(self, ctx: McpContext) -> list[dict]:
        rows = await AccountService.list_for_family(ctx.db, ctx.family_id)
        return [_ser(a) for a in rows]

    async def get(self, ctx: McpContext, entity_id: UUID) -> dict:
        return _ser(await AccountService.get_by_id(ctx.db, entity_id, ctx.family_id))

    async def create(self, ctx: McpContext, data: dict) -> dict:
        payload = dict(data)
        if "account_type" in payload:
            payload["type"] = payload.pop("account_type")
        a = await AccountService.create(
            ctx.db,
            family_id=ctx.family_id,
            data=AppAccountCreate(**payload),
            user_id=ctx.user_id,
        )
        return _ser(a)

    async def update(self, ctx: McpContext, entity_id: UUID, data: dict) -> dict:
        payload = dict(data)
        if "account_type" in payload:
            payload["type"] = payload.pop("account_type")
        a = await AccountService.update(
            ctx.db,
            account_id=entity_id,
            family_id=ctx.family_id,
            data=AppAccountUpdate(**payload),
        )
        return _ser(a)

    async def delete(self, ctx: McpContext, entity_id: UUID) -> None:
        await AccountService.delete_by_id(ctx.db, entity_id, ctx.family_id)
