"""MCP adapters for the calendar domain.

Migrated from the legacy ``create_calendar_event`` handler. Accepts a naive
ISO timestamp and treats it as UTC, matching the prior behavior.
"""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select

from app.mcp.adapters import ServiceAdapter
from app.mcp.context import McpContext
from app.models.calendar_event import CalendarEvent


def _ser(e: CalendarEvent) -> dict:
    return {
        "id": str(e.id),
        "title": e.title,
        "start_ts": e.start_ts.isoformat() if e.start_ts else None,
        "location": e.location,
    }


class EventAdapter(ServiceAdapter):
    async def list(self, ctx: McpContext) -> list[dict]:
        q = (
            select(CalendarEvent)
            .where(CalendarEvent.family_id == ctx.family_id)
            .order_by(CalendarEvent.start_ts.desc())
            .limit(50)
        )
        rows = list((await ctx.db.execute(q)).scalars().all())
        return [_ser(e) for e in rows]

    async def get(self, ctx: McpContext, entity_id: UUID) -> dict:
        q = select(CalendarEvent).where(
            CalendarEvent.id == entity_id,
            CalendarEvent.family_id == ctx.family_id,
        )
        e = (await ctx.db.execute(q)).scalar_one_or_none()
        if e is None:
            raise ValueError("CalendarEvent not found")
        return _ser(e)

    async def create(self, ctx: McpContext, data: dict) -> dict:
        from app.schemas.calendar_event import CalendarEventCreate
        from app.services.calendar_service import CalendarService

        start = datetime.fromisoformat(data["start_iso"])
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        payload = CalendarEventCreate(
            title=str(data["title"])[:200],
            start_ts=start,
            all_day=bool(data.get("all_day", False)),
            location=data.get("location"),
            source="manual",
        )
        evt = await CalendarService.create_event(
            ctx.db, payload, ctx.family_id, ctx.user_id
        )
        return _ser(evt)

    async def update(self, ctx: McpContext, entity_id: UUID, data: dict) -> dict:
        from app.schemas.calendar_event import CalendarEventUpdate
        from app.services.calendar_service import CalendarService

        payload = CalendarEventUpdate(**data)
        evt = await CalendarService.update_event(
            ctx.db, entity_id, payload, ctx.family_id
        )
        return _ser(evt)

    async def delete(self, ctx: McpContext, entity_id: UUID) -> None:
        from app.services.calendar_service import CalendarService

        await CalendarService.delete_event(ctx.db, entity_id, ctx.family_id)
