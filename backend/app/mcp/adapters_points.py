"""
MCP ServiceAdapter subclasses for points-domain entities:
  ledger (list/get), adjust (create), transfer (create).

Family scope comes from McpContext; never from adapter arguments.
PointTransaction has no family_id column — scope is enforced by joining
through the users table (user.family_id) in the list query.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.mcp.adapters import ServiceAdapter
from app.mcp.context import McpContext


# ── serializer ─────────────────────────────────────────────────────────────

def _ser_txn(t) -> dict:
    return {
        "id": str(t.id),
        "type": t.type.value if hasattr(t.type, "value") else str(t.type),
        "points": t.points,
        "description": t.description,
        "user_id": str(t.user_id),
        "balance_before": t.balance_before,
        "balance_after": t.balance_after,
        "task_id": str(t.task_id) if t.task_id else None,
        "reward_id": str(t.reward_id) if t.reward_id else None,
        "created_by": str(t.created_by) if t.created_by else None,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


# ── ledger ─────────────────────────────────────────────────────────────────

class LedgerAdapter(ServiceAdapter):
    """Read-only view of PointTransaction rows scoped to the family.

    PointTransaction has no family_id column; scope is enforced by joining
    through the User table so we only return rows belonging to users of
    the caller's family.
    """

    async def list(self, ctx: McpContext) -> list[dict]:
        from app.models import PointTransaction, User
        stmt = (
            select(PointTransaction)
            .join(User, User.id == PointTransaction.user_id)
            .where(User.family_id == ctx.family_id)
            .order_by(PointTransaction.created_at.desc())
            .limit(200)
        )
        result = await ctx.db.execute(stmt)
        rows = list(result.scalars().all())
        return [_ser_txn(r) for r in rows]

    async def get(self, ctx: McpContext, entity_id: UUID) -> dict:
        from app.models import PointTransaction, User
        from app.core.exceptions import NotFoundException, ForbiddenException
        stmt = (
            select(PointTransaction)
            .join(User, User.id == PointTransaction.user_id)
            .where(
                PointTransaction.id == entity_id,
                User.family_id == ctx.family_id,
            )
        )
        result = await ctx.db.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            raise NotFoundException(f"PointTransaction {entity_id} not found for family")
        return _ser_txn(row)


# ── adjust ─────────────────────────────────────────────────────────────────

class AdjustAdapter(ServiceAdapter):
    """Parent-adjustment create adapter.

    create is the only supported op; it is a money-moving op (gated by
    destructive_ops in the EntitySpec).
    """

    async def create(self, ctx: McpContext, data: dict) -> dict:
        from app.services.points_service import PointsService
        from app.schemas.points import ParentAdjustment
        payload = dict(data)
        # Ensure user_id is a UUID (may come as string from JSON)
        if isinstance(payload.get("user_id"), str):
            payload["user_id"] = UUID(payload["user_id"])
        adjustment = ParentAdjustment(**payload)
        txn = await PointsService.create_parent_adjustment(
            db=ctx.db,
            adjustment=adjustment,
            parent_id=ctx.user_id,
            family_id=ctx.family_id,
        )
        return _ser_txn(txn)


# ── transfer ───────────────────────────────────────────────────────────────

class TransferAdapter(ServiceAdapter):
    """Point transfer create adapter.

    create is the only supported op; it is a money-moving op (gated by
    destructive_ops in the EntitySpec).
    Returns both the debit and credit transactions.
    """

    async def create(self, ctx: McpContext, data: dict) -> dict:
        from app.services.points_service import PointsService
        from app.schemas.points import PointTransfer
        payload = dict(data)
        for field in ("from_user_id", "to_user_id"):
            if isinstance(payload.get(field), str):
                payload[field] = UUID(payload[field])
        transfer = PointTransfer(**payload)
        debit, credit = await PointsService.transfer_points(
            db=ctx.db,
            transfer=transfer,
            family_id=ctx.family_id,
        )
        return {"debit": _ser_txn(debit), "credit": _ser_txn(credit)}
