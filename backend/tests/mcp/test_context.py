import pytest
from uuid import uuid4
from app.mcp.context import McpContext, get_context, use_context, McpContextError


@pytest.mark.asyncio
async def test_context_set_and_cleared():
    with pytest.raises(McpContextError):
        get_context()
    ctx = McpContext(family_id=uuid4(), user_id=uuid4(), role="PARENT", db=None)
    async with use_context(ctx):
        assert get_context().family_id == ctx.family_id
    with pytest.raises(McpContextError):
        get_context()
