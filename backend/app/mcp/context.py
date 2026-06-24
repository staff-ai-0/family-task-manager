from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession


class McpContextError(RuntimeError):
    pass


@dataclass
class McpContext:
    family_id: UUID
    user_id: UUID | None
    role: str
    db: AsyncSession


current_context: ContextVar["McpContext | None"] = ContextVar("mcp_current_context", default=None)


def get_context() -> McpContext:
    ctx = current_context.get()
    if ctx is None:
        raise McpContextError("MCP tool called with no family context bound")
    return ctx


@asynccontextmanager
async def use_context(ctx: McpContext):
    token = current_context.set(ctx)
    try:
        yield ctx
    finally:
        current_context.reset(token)
