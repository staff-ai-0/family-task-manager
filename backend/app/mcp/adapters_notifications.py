"""MCP adapters for the notifications domain.

Migrated from the legacy ``send_family_notification`` (create, family-wide)
and ``list_recent_notifications`` (read) handlers.
"""

from uuid import UUID

from sqlalchemy import select

from app.mcp.adapters import ServiceAdapter
from app.mcp.context import McpContext
from app.models.notification import Notification, NotificationType


def _ser(n: Notification) -> dict:
    return {
        "id": str(n.id),
        "type": str(n.type),
        "title": n.title,
        "body": n.body,
        "is_read": n.is_read,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }


class NotificationAdapter(ServiceAdapter):
    async def list(self, ctx: McpContext) -> list[dict]:
        q = (
            select(Notification)
            .where(Notification.family_id == ctx.family_id)
            .order_by(Notification.created_at.desc())
            .limit(20)
        )
        rows = list((await ctx.db.execute(q)).scalars().all())
        return [_ser(n) for n in rows]

    async def get(self, ctx: McpContext, entity_id: UUID) -> dict:
        q = select(Notification).where(
            Notification.id == entity_id,
            Notification.family_id == ctx.family_id,
        )
        n = (await ctx.db.execute(q)).scalar_one_or_none()
        if n is None:
            raise ValueError("Notification not found")
        return _ser(n)

    async def create(self, ctx: McpContext, data: dict) -> dict:
        from app.services.notification_service import NotificationService

        n = await NotificationService.create(
            ctx.db,
            family_id=ctx.family_id,
            user_id=None,  # family-wide broadcast
            type=NotificationType.SHOPPING_ITEM_ADDED,
            title=str(data["title"])[:200],
            body=data.get("body"),
            link="/notifications",
            push=False,
        )
        return _ser(n)

    async def delete(self, ctx: McpContext, entity_id: UUID) -> None:
        q = select(Notification).where(
            Notification.id == entity_id,
            Notification.family_id == ctx.family_id,
        )
        n = (await ctx.db.execute(q)).scalar_one_or_none()
        if n is None:
            raise ValueError("Notification not found")
        await ctx.db.delete(n)
        await ctx.db.commit()
