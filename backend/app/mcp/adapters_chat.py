"""MCP adapters for the chat domain.

chat.message supports LGCD (list / get / create / delete — no update).
Delete is the only destructive op.

Reading chat content (list/get) exposes KID-written messages to the LLM, so
it is gated on the family's parental AI-processing opt-in
(families.ai_processing_consent). Create/delete stay open: posting a message
on the parent's behalf or deleting one does not feed kid content to the model.
"""

from uuid import UUID

from app.mcp.adapters import ServiceAdapter
from app.mcp.context import McpContext
from app.models.family_chat import FamilyChatMessage
from app.services.base_service import BaseFamilyService
from app.services.family_chat_service import FamilyChatService

# Returned verbatim to the model instead of message content when the family
# has not opted in to AI processing of kid-generated content.
AI_CHAT_ACCESS_DISABLED = {
    "error": "ai_chat_access_disabled",
    "detail": (
        "AI access to family chat is disabled by family settings. "
        "A parent can enable it in Settings > Family (AI processing consent)."
    ),
}


async def _chat_read_allowed(ctx: McpContext) -> bool:
    from app.services.family_service import FamilyService

    return await FamilyService.has_ai_processing_consent(ctx.db, ctx.family_id)


def _ser(m: FamilyChatMessage) -> dict:
    return {
        "id": str(m.id),
        "body": m.body,
        "sender_id": str(m.sender_id) if m.sender_id else None,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


class _MessageBase(BaseFamilyService[FamilyChatMessage]):
    model = FamilyChatMessage


class MessageAdapter(ServiceAdapter):
    async def list(self, ctx: McpContext) -> list[dict]:
        if not await _chat_read_allowed(ctx):
            return [AI_CHAT_ACCESS_DISABLED]
        rows = await FamilyChatService.list_messages(ctx.db, ctx.family_id, limit=50)
        return [_ser(m) for m in rows]

    async def get(self, ctx: McpContext, entity_id: UUID) -> dict:
        if not await _chat_read_allowed(ctx):
            return AI_CHAT_ACCESS_DISABLED
        m = await _MessageBase.get_by_id(ctx.db, entity_id, ctx.family_id)
        return _ser(m)

    async def create(self, ctx: McpContext, data: dict) -> dict:
        # sender_id from context — never trust client-supplied value
        sender_id = ctx.user_id
        m = await FamilyChatService.post_message(
            ctx.db,
            family_id=ctx.family_id,
            sender_id=sender_id,
            body=data["body"],
        )
        return _ser(m)

    async def delete(self, ctx: McpContext, entity_id: UUID) -> None:
        await _MessageBase.delete_by_id(ctx.db, entity_id, ctx.family_id)
