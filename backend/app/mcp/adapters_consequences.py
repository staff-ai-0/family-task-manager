"""MCP ServiceAdapter subclasses for the consequences domain.

Consequence domain: LGCUD (delete is destructive).

ConsequenceService subclasses BaseFamilyService[Consequence] so get/delete
use the inherited family-scoped classmethods. create/update/list use the
explicit ConsequenceService static methods.
"""
from __future__ import annotations

from uuid import UUID

from app.mcp.adapters import ServiceAdapter
from app.mcp.context import McpContext


def _ser_consequence(c) -> dict:
    return {
        "id": str(c.id),
        "family_id": str(c.family_id),
        "title": c.title,
        "description": c.description,
        "severity": c.severity.value if hasattr(c.severity, "value") else str(c.severity),
        "restriction_type": c.restriction_type.value if hasattr(c.restriction_type, "value") else str(c.restriction_type),
        "duration_days": c.duration_days,
        "active": c.active,
        "resolved": c.resolved,
        "applied_to_user": str(c.applied_to_user),
        "triggered_by_task_id": str(c.triggered_by_task_id) if c.triggered_by_task_id else None,
        "start_date": c.start_date.isoformat() if c.start_date else None,
        "end_date": c.end_date.isoformat() if c.end_date else None,
        "resolved_at": c.resolved_at.isoformat() if c.resolved_at else None,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


class ConsequenceAdapter(ServiceAdapter):
    """Wraps ConsequenceService for LGCUD.

    Family scope always comes from McpContext; never from adapter arguments.
    """

    async def list(self, ctx: McpContext) -> list[dict]:
        from app.services.consequence_service import ConsequenceService
        rows = await ConsequenceService.list_consequences(ctx.db, ctx.family_id)
        return [_ser_consequence(c) for c in rows]

    async def get(self, ctx: McpContext, entity_id: UUID) -> dict:
        from app.services.consequence_service import ConsequenceService
        c = await ConsequenceService.get_consequence(ctx.db, entity_id, ctx.family_id)
        return _ser_consequence(c)

    async def create(self, ctx: McpContext, data: dict) -> dict:
        from app.services.consequence_service import ConsequenceService
        from app.schemas.consequence import ConsequenceCreate
        from app.models.consequence import ConsequenceSeverity, RestrictionType

        # Coerce string enum values to the correct types
        payload = dict(data)
        if "severity" in payload and isinstance(payload["severity"], str):
            payload["severity"] = ConsequenceSeverity(payload["severity"])
        if "restriction_type" in payload and isinstance(payload["restriction_type"], str):
            payload["restriction_type"] = RestrictionType(payload["restriction_type"])

        consequence_data = ConsequenceCreate(**payload)
        c = await ConsequenceService.create_consequence(ctx.db, consequence_data, ctx.family_id)
        return _ser_consequence(c)

    async def update(self, ctx: McpContext, entity_id: UUID, data: dict) -> dict:
        from app.services.consequence_service import ConsequenceService
        from app.schemas.consequence import ConsequenceUpdate
        from app.models.consequence import ConsequenceSeverity, RestrictionType

        payload = dict(data)
        if "severity" in payload and isinstance(payload.get("severity"), str):
            payload["severity"] = ConsequenceSeverity(payload["severity"])
        if "restriction_type" in payload and isinstance(payload.get("restriction_type"), str):
            payload["restriction_type"] = RestrictionType(payload["restriction_type"])

        consequence_data = ConsequenceUpdate(**payload)
        c = await ConsequenceService.update_consequence(ctx.db, entity_id, consequence_data, ctx.family_id)
        return _ser_consequence(c)

    async def delete(self, ctx: McpContext, entity_id: UUID) -> None:
        from app.services.consequence_service import ConsequenceService
        await ConsequenceService.delete_consequence(ctx.db, entity_id, ctx.family_id)
