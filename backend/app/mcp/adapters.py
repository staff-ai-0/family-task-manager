from uuid import UUID
from app.mcp.context import McpContext


class ServiceAdapter:
    """Binds a generic CRUD op to a concrete app Service. Override what the entity supports."""

    async def list(self, ctx: McpContext) -> list[dict]:
        raise NotImplementedError

    async def get(self, ctx: McpContext, entity_id: UUID) -> dict:
        raise NotImplementedError

    async def create(self, ctx: McpContext, data: dict) -> dict:
        raise NotImplementedError

    async def update(self, ctx: McpContext, entity_id: UUID, data: dict) -> dict:
        raise NotImplementedError

    async def delete(self, ctx: McpContext, entity_id: UUID) -> None:
        raise NotImplementedError
