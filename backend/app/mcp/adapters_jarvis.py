"""MCP adapters for the jarvis (scheduled prompts) domain.

Migrated from the legacy ``schedule_jarvis_prompt`` handler.
"""

from uuid import UUID

from app.mcp.adapters import ServiceAdapter
from app.mcp.context import McpContext


def _ser(s) -> dict:
    return {
        "id": str(s.id),
        "name": s.name,
        "cron_expr": s.cron_expr,
        "channel": s.channel,
        "next_run_at": s.next_run_at.isoformat() if s.next_run_at else None,
    }


class ScheduleAdapter(ServiceAdapter):
    async def list(self, ctx: McpContext) -> list[dict]:
        from app.services.jarvis_schedule_service import JarvisScheduleService

        rows = await JarvisScheduleService.list(ctx.db, ctx.family_id)
        return [_ser(s) for s in rows]

    async def create(self, ctx: McpContext, data: dict) -> dict:
        from app.services.jarvis_schedule_service import JarvisScheduleService

        s = await JarvisScheduleService.create(
            ctx.db,
            family_id=ctx.family_id,
            created_by=ctx.user_id,
            name=str(data["name"])[:120],
            prompt=str(data["prompt"])[:2000],
            cron_expr=str(data["cron_expr"])[:64],
            channel=str(data.get("channel", "notification")),
        )
        return _ser(s)

    async def delete(self, ctx: McpContext, entity_id: UUID) -> None:
        from app.services.jarvis_schedule_service import JarvisScheduleService

        await JarvisScheduleService.delete(ctx.db, entity_id, ctx.family_id)
